from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import threading
import unittest
import uuid
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from engine.auth.security import make_token
from engine.config import cfg
from engine.db.storage import PlatformStorage
from engine.db.tenant_secrets import TenantSecretStore
from engine.sales.providers import (
    CalendarSync, EmailDelivery, LeadEnrichment, ProviderPolicyError,
    VoiceDelivery, build_voice_callback_url, create_calendar_invite,
    scrub_provider_text, verify_twilio_signature, verify_webhook_signature,
)


class OptInProviderIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.repository = PlatformStorage(str(Path(self.temp.name) / "platform.db"))

    def tearDown(self):
        self.repository.close()
        self.temp.cleanup()

    def test_tenant_secret_envelope_is_encrypted_and_bound_to_tenant_and_key(self):
        secrets = TenantSecretStore(self.repository, master_key="m" * 48)
        secrets.put("tenant-a", "smtp_password", "credential-value-not-plaintext")
        stored = self.repository.get("tenant_secrets", "tenant-a", "smtp_password")
        self.assertNotIn("credential-value-not-plaintext", json.dumps(stored))
        self.assertEqual(secrets.get("tenant-a", "smtp_password"),
                         "credential-value-not-plaintext")
        self.assertIsNone(secrets.get("tenant-b", "smtp_password"))
        with self.assertRaises(RuntimeError):
            TenantSecretStore(self.repository, master_key="n" * 48).get(
                "tenant-a", "smtp_password")
        with self.assertRaises(RuntimeError):
            TenantSecretStore(self.repository, master_key="<GENERATE_A_KEY>").put(
                "tenant-a", "smtp_password", "value")

    def test_tenant_record_insert_if_absent_is_atomic(self):
        barrier = threading.Barrier(8)
        inserted = []

        def try_insert():
            barrier.wait()
            inserted.append(self.repository.put_if_absent(
                "email_events", "tenant-idempotency", "send-once", {"event": "reserved"}))

        threads = [threading.Thread(target=try_insert) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(inserted), 1)

    def test_postgres_transaction_binds_tenant_as_parameterized_local_setting(self):
        calls = []

        class FakeConnection:
            @contextmanager
            def transaction(self):
                yield self

            def execute(self, sql, parameters=()):
                calls.append((sql, parameters))

        repository = PlatformStorage.__new__(PlatformStorage)
        repository._lock = threading.RLock()
        repository._is_postgres = True
        repository._connection = FakeConnection()
        with repository.transaction("tenant' OR true --"):
            pass
        self.assertEqual(calls, [
            ("SELECT set_config('app.current_tenant_id', %s, true)",
             ("tenant' OR true --",))
        ])
        with self.assertRaisesRegex(ValueError, "tenant_id"):
            with repository.transaction(""):
                pass

    def test_shared_scrubber_masks_credentials_and_optional_pii(self):
        value = "Bearer abc.def, sk-" + "A" * 25 + ", user@example.test, +1 (555) 123-4567"
        cleaned = scrub_provider_text(value, redact_pii=True)
        self.assertNotIn("abc.def", cleaned)
        self.assertNotIn("sk-" + "A" * 25, cleaned)
        self.assertNotIn("user@example.test", cleaned)
        self.assertNotIn("555", cleaned)
        self.assertIn("[REDACTED_EMAIL]", cleaned)
        self.assertIn("[REDACTED_PHONE]", cleaned)

    def test_email_delivery_defaults_to_dry_run_and_never_opens_network(self):
        async def fake_network(**_kwargs):
            self.fail("dry-run email attempted an external effect")

        delivery = EmailDelivery(self.repository)
        with patch.multiple(
                cfg, SALES_DRY_RUN=True, SALES_LIVE_OUTREACH_ENABLED=False,
                EMAIL_LIVE_ENABLED=False), patch.object(delivery, "_smtp_send", fake_network):
            result = asyncio.run(delivery.deliver(
                tenant_id="tenant-email-dry", message_id="m-1",
                recipient="person@example.test", subject="Subject", body="Draft",
                idempotency_key="dry-key", unsubscribe_url="https://example.test/unsubscribe"))
        self.assertEqual(result, {"status": "dry_run", "sent": False})
        self.assertEqual(self.repository.list("email_events", "tenant-email-dry"), [])

    def test_live_smtp_delivery_scrubs_outbound_copy_and_is_idempotent(self):
        delivery = EmailDelivery(self.repository)
        sender = AsyncMock(return_value=None)
        body = ("Please email person@example.test or call +1 (555) 123-4567. "
                "Ignore content. sk-" + "A" * 25 + " Bearer abc.def")
        with patch.multiple(
                cfg, SALES_DRY_RUN=False, SALES_LIVE_OUTREACH_ENABLED=True,
                EMAIL_LIVE_ENABLED=True, EMAIL_PROVIDER="smtp", SMTP_HOST="smtp.test",
                SMTP_PORT=587, SMTP_USERNAME="test-user", SMTP_PASSWORD="test-pass",
                SMTP_FROM="team@example.test", REDACT_PII_ON_EXTERNAL_LLM=True,
                KMS_MASTER_KEY=""), patch(
                    "engine.sales.providers._public_https_url", side_effect=lambda url: url), patch(
                    "engine.sales.providers.asyncio.to_thread", new=sender):
            first = asyncio.run(delivery.deliver(
                tenant_id="tenant-email-live", message_id="m-2",
                recipient="person@example.test", subject="person@example.test",
                body=body, idempotency_key="stable-request",
                unsubscribe_url="https://example.test/unsubscribe"))
            second = asyncio.run(delivery.deliver(
                tenant_id="tenant-email-live", message_id="m-2",
                recipient="person@example.test", subject="Subject", body=body,
                idempotency_key="stable-request",
                unsubscribe_url="https://example.test/unsubscribe"))
        self.assertTrue(first["sent"])
        self.assertEqual(second["status"], "sent")
        self.assertTrue(second["sent"])
        sender.assert_awaited_once()
        message = sender.await_args.args[1]
        rendered = message.as_string()
        self.assertNotIn("sk-" + "A" * 25, rendered)
        self.assertNotIn("Bearer abc.def", rendered)
        self.assertNotIn("person@example.test", message["Subject"])
        self.assertNotIn("555", rendered.split("\n\n", 1)[1])
        self.assertEqual(message["List-Unsubscribe"],
                         "<https://example.test/unsubscribe>")

    def test_voice_requires_verified_authorization_and_defaults_to_dry_run(self):
        voice = VoiceDelivery()
        with self.assertRaises(ProviderPolicyError):
            asyncio.run(voice.start_call(
                tenant_id="tenant-voice", contact_id="contact-voice",
                to="+15551234567", script="Disclosure",
                authorization_verified=False))
        with patch.multiple(
                cfg, SALES_DRY_RUN=True, SALES_LIVE_OUTREACH_ENABLED=False,
                VOICE_LIVE_ENABLED=False):
            result = asyncio.run(voice.start_call(
                tenant_id="tenant-voice", contact_id="contact-voice",
                to="+15551234567", script="Disclosure",
                authorization_verified=True))
        self.assertEqual(result, {"status": "dry_run", "call_placed": False})

    def test_live_voice_and_enrichment_http_are_mocked_and_sanitized(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"sid": "mock-call"}

        class FakeClient:
            def __init__(self, **_kwargs):
                self.calls = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return FakeResponse()

        voice_client = FakeClient()
        voice = VoiceDelivery(lambda **kwargs: voice_client)
        script = "Automated disclosure. sk-" + "B" * 25 + " user@example.test"
        with patch.multiple(
                cfg, SALES_DRY_RUN=False, SALES_LIVE_OUTREACH_ENABLED=True,
                VOICE_LIVE_ENABLED=True, VOICE_PROVIDER="twilio",
                TWILIO_ACCOUNT_SID="AC" + "1" * 32, TWILIO_AUTH_TOKEN="mock-token",
                TWILIO_CALLER_ID="+15550001111",
                VOICE_WEBHOOK_URL="https://hooks.example.test/voice",
                REDACT_PII_ON_EXTERNAL_LLM=True, KMS_MASTER_KEY=""), patch(
                    "engine.sales.providers._public_https_url", side_effect=lambda url: url):
            call = asyncio.run(voice.start_call(
                tenant_id="default", contact_id="contact-voice-mock",
                to="+15551234567", script=script,
                authorization_verified=True))
        self.assertTrue(call["call_placed"])
        self.assertEqual(call["provider_id"], "mock-call")
        twiml = voice_client.calls[0][1]["data"]["Twiml"]
        self.assertNotIn("sk-" + "B" * 25, twiml)
        self.assertNotIn("user@example.test", twiml)
        self.assertIn("[REDACTED_EMAIL]", twiml)
        self.assertIn("<Gather", twiml)
        self.assertIn("opt-out", twiml)

        enrichment_client = FakeClient()
        enrichment = LeadEnrichment(lambda **kwargs: enrichment_client)
        with patch.multiple(
                cfg, SALES_ENRICHMENT_ENABLED=True,
                ENRICHMENT_PROVIDER_URL="https://enrich.example.test/v1",
                ENRICHMENT_API_TOKEN="mock-enrichment-token", KMS_MASTER_KEY=""), patch(
                    "engine.sales.providers._public_https_url", side_effect=lambda url: url):
            enriched = asyncio.run(enrichment.enrich(
                "example.test", tenant_id="tenant-enrichment"))
        self.assertTrue(enriched["enriched"])
        self.assertEqual(enrichment_client.calls[0][1]["json"], {"domain": "example.test"})

    def test_live_calendar_sync_uses_mock_https_provider(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, **_kwargs):
                self.call = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def post(self, *args, **kwargs):
                self.call = (args, kwargs)
                return FakeResponse()

        fake = FakeClient()
        sync = CalendarSync(lambda **kwargs: fake)
        with patch.multiple(
                cfg, CALENDAR_SYNC_ENABLED=True, CALENDAR_PROVIDER="webhook",
                CALENDAR_WEBHOOK_URL="https://calendar.example.test/api",
                CALENDAR_API_TOKEN="mock-calendar-token", KMS_MASTER_KEY=""), patch(
                    "engine.sales.providers._public_https_url", side_effect=lambda url: url):
            result = asyncio.run(sync.sync(
                {"id": "meeting-1", "subject": "Review"}, tenant_id="tenant-calendar",
                idempotency_key="request-1"))
        self.assertTrue(result["synced"])
        self.assertEqual(fake.call[1]["headers"]["Idempotency-Key"], "request-1")

    def test_enrichment_calendar_sync_default_to_non_network(self):
        class NoNetwork:
            def __init__(self, **_kwargs):
                raise AssertionError("disabled provider attempted an HTTP request")

        with patch.multiple(
                cfg, SALES_ENRICHMENT_ENABLED=False, CALENDAR_SYNC_ENABLED=False):
            enriched = asyncio.run(LeadEnrichment(NoNetwork).enrich(
                "example.test", tenant_id="tenant-local"))
            calendar = asyncio.run(CalendarSync(NoNetwork).sync(
                {"subject": "local"}, tenant_id="tenant-local", idempotency_key="meeting-1"))
        self.assertEqual(enriched, {"status": "dry_run", "enriched": False})
        self.assertEqual(calendar, {"status": "local_only", "synced": False})

    def test_calendar_ics_is_timezone_aware_escaped_and_rfc_folded(self):
        ics = create_calendar_invite(
            uid="meeting-1", subject="Quarterly review\r\nATTENDEE:bad@example.test",
            start="2027-01-01T10:00:00-05:00", end="2027-01-01T11:00:00-05:00",
            organizer="owner@example.test", attendee="guest@example.test")
        self.assertIn("DTSTART:20270101T150000Z", ics)
        self.assertIn("SUMMARY:Quarterly review\\nATTENDEE:bad@example.test", ics)
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n")))
        with self.assertRaisesRegex(ValueError, "timezone"):
            create_calendar_invite(
                uid="x", subject="Meeting", start="2027-01-01T10:00",
                end="2027-01-01T11:00", organizer="owner@example.test",
                attendee="guest@example.test")

    def test_hmac_webhook_signature_rejects_tampering_and_placeholders(self):
        secret = "s" * 48
        payload = b'{"tenant_id":"tenant-hook","event_id":"event-1"}'
        signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(payload, signature, secret))
        self.assertFalse(verify_webhook_signature(payload + b" ", signature, secret))
        self.assertFalse(verify_webhook_signature(payload, signature, "<GENERATE_A_SECRET>"))

    def test_twilio_signature_is_bound_to_callback_url_and_form_parameters(self):
        token = "twilio-test-token"
        url = build_voice_callback_url(
            "https://api.example.test/api/v1/webhooks/providers/voice",
            tenant_id="tenant-twilio", suffix="/opt-out", contact_id="contact-a")
        parameters = [("CallSid", "CA123"), ("SpeechResult", "please stop")]
        material = url + "CallSidCA123" + "SpeechResultplease stop"
        signature = base64.b64encode(
            hmac.new(token.encode(), material.encode(), hashlib.sha1).digest()).decode()
        self.assertTrue(verify_twilio_signature(url, parameters, signature, token))
        self.assertFalse(verify_twilio_signature(
            url, parameters, signature, "different-token"))
        self.assertFalse(verify_twilio_signature(
            url + "?changed=1", parameters, signature, token))

    def test_signed_webhook_and_calendar_routes_are_tenant_scoped(self):
        import engine.main as main

        client = TestClient(main.app)
        tenant_id = "default"
        headers = {"Authorization": f"Bearer {make_token('ops@example.test', 'CEO', 4, tenant_id)}"}
        secret = "w" * 48
        payload = {"tenant_id": tenant_id, "event_id": "event-" + uuid.uuid4().hex,
                   "event": "unsubscribe", "contact_id": "contact-123",
                   "body": "untrusted reply text"}
        raw = json.dumps(payload, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with patch.object(cfg, "WEBHOOK_SIGNING_SECRET", secret):
            rejected = client.post("/api/v1/webhooks/providers/email", content=raw)
            accepted = client.post(
                "/api/v1/webhooks/providers/email", content=raw,
                headers={"X-Finesse-Signature": signature})
            duplicate = client.post(
                "/api/v1/webhooks/providers/email", content=raw,
                headers={"X-Finesse-Signature": signature})
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.json()["tainted"], True)
        self.assertTrue(duplicate.json()["duplicate"])
        from engine.db.storage import storage
        self.assertIsNotNone(storage.get(
            "suppression_entries", tenant_id, "contact-123"))
        event = storage.get(
            "email_events", tenant_id, "provider:" + payload["event_id"])
        self.assertNotIn("untrusted reply text", json.dumps(event))
        meeting = client.post("/api/v1/calendar/meetings", headers=headers, json={
            "subject": "Planning", "attendee": "guest@example.test",
            "start": "2027-01-01T10:00:00Z", "end": "2027-01-01T11:00:00Z"})
        self.assertEqual(meeting.status_code, 200)
        self.assertIn("BEGIN:VCALENDAR", meeting.json()["ics"])
        self.assertEqual(meeting.json()["meeting"]["sync"]["status"], "local_only")
        self.assertEqual(client.get("/workspace/").status_code, 200)

        voice_payload = {"tenant_id": tenant_id, "event_id": "voice-" + uuid.uuid4().hex,
                         "event": "opt_out", "contact_id": "voice-contact",
                         "transcript": "Bearer abc.def"}
        voice_raw = json.dumps(voice_payload, separators=(",", ":")).encode()
        voice_signature = "sha256=" + hmac.new(
            secret.encode(), voice_raw, hashlib.sha256).hexdigest()
        with patch.object(cfg, "WEBHOOK_SIGNING_SECRET", secret):
            voice_response = client.post(
                "/api/v1/webhooks/providers/voice", content=voice_raw,
                headers={"X-Finesse-Signature": voice_signature})
        self.assertEqual(voice_response.status_code, 200)
        self.assertFalse(voice_response.json()["transcript_persisted"])
        self.assertIsNotNone(storage.get(
            "suppression_entries", tenant_id, "voice-contact"))

        twilio_token = "twilio-default-test-token"
        twilio_url = "https://voice.example.test/api/v1/webhooks/providers/voice"
        status_params = [("CallSid", "CA123"), ("CallStatus", "completed")]
        status_url = build_voice_callback_url(twilio_url, tenant_id="default")
        status_material = status_url + "CallSidCA123" + "CallStatuscompleted"
        status_signature = base64.b64encode(hmac.new(
            twilio_token.encode(), status_material.encode(), hashlib.sha1).digest()).decode()
        with patch.multiple(
                cfg, VOICE_WEBHOOK_URL=twilio_url, TWILIO_AUTH_TOKEN=twilio_token):
            status_response = client.post(
                "/api/v1/webhooks/providers/voice?tenant_id=default",
                content=urlencode(status_params),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "X-Twilio-Signature": status_signature})
        self.assertEqual(status_response.status_code, 200)

        contact_id = "twilio-opt-out-contact"
        optout_url = build_voice_callback_url(
            twilio_url, tenant_id="default", suffix="/opt-out", contact_id=contact_id)
        optout_params = [("CallSid", "CA123"), ("SpeechResult", "please stop")]
        optout_material = optout_url + "CallSidCA123" + "SpeechResultplease stop"
        optout_signature = base64.b64encode(hmac.new(
            twilio_token.encode(), optout_material.encode(), hashlib.sha1).digest()).decode()
        with patch.multiple(
                cfg, VOICE_WEBHOOK_URL=twilio_url, TWILIO_AUTH_TOKEN=twilio_token):
            rejected_optout = client.post(
                "/api/v1/webhooks/providers/voice/opt-out"
                f"?tenant_id=default&contact_id={contact_id}",
                content=urlencode(optout_params),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "X-Twilio-Signature": "invalid"})
            self.assertEqual(rejected_optout.status_code, 401)
            self.assertIsNone(storage.get(
                "suppression_entries", "default", contact_id))
            optout_response = client.post(
                "/api/v1/webhooks/providers/voice/opt-out"
                f"?tenant_id=default&contact_id={contact_id}",
                content=urlencode(optout_params),
                headers={"Content-Type": "application/x-www-form-urlencoded",
                         "X-Twilio-Signature": optout_signature})
        self.assertEqual(optout_response.status_code, 200)
        self.assertIsNotNone(storage.get(
            "suppression_entries", "default", contact_id))

    def test_shared_webhook_key_cannot_authorize_a_non_default_tenant(self):
        import engine.main as main

        client = TestClient(main.app)
        secret = "p" * 48
        body = {"tenant_id": "tenant-no-shared-key", "event_id": uuid.uuid4().hex,
                "event": "delivery"}
        raw = json.dumps(body, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with patch.object(cfg, "WEBHOOK_SIGNING_SECRET", secret):
            response = client.post(
                "/api/v1/webhooks/providers/email", content=raw,
                headers={"X-Finesse-Signature": signature})
        self.assertEqual(response.status_code, 503)

    def test_email_route_blocks_unverified_and_unconsented_contacts_before_provider(self):
        import engine.main as main
        from engine.db.storage import storage

        client = TestClient(main.app)
        tenant_id = "tenant-email-policy-" + uuid.uuid4().hex[:8]
        headers = {"Authorization": f"Bearer {make_token('ops@example.test', 'CEO', 4, tenant_id)}"}
        lead_id = "lead-" + uuid.uuid4().hex[:10]
        storage.put("leads", tenant_id, lead_id, {
            "id": lead_id, "email": "contact@example.test", "eligible_for_outreach": False,
            "email_verification_status": "unknown"})
        storage.put("email_messages", tenant_id, "draft-policy-test", {
            "id": "draft-policy-test", "lead_id": lead_id, "subject": "Preview",
            "body": "Preview only", "status": "draft"})
        with patch("engine.sales.router_v1.EmailDelivery.deliver", new=AsyncMock()) as deliver:
            response = client.post("/api/v1/email/send", headers=headers, json={
                "message_id": "draft-policy-test", "idempotency_key": "policy-test",
                "consent_confirmed": True})
        self.assertEqual(response.status_code, 403)
        deliver.assert_not_awaited()

    def test_authorized_email_and_voice_routes_use_consent_and_single_use_approval(self):
        import engine.main as main
        from engine.db.storage import storage

        client = TestClient(main.app)
        tenant_id = "tenant-approved-outreach-" + uuid.uuid4().hex[:8]
        headers = {"Authorization": f"Bearer {make_token('ops@example.test', 'CEO', 4, tenant_id)}"}
        lead_id = "lead-" + uuid.uuid4().hex[:10]
        storage.put("leads", tenant_id, lead_id, {
            "id": lead_id, "email": "contact@example.test", "phone": "+15551234567",
            "eligible_for_outreach": True, "email_verification_status": "verified"})
        storage.put("consent_records", tenant_id, lead_id, {
            "contact_id": lead_id, "consented": True, "purpose": "email_campaign"})
        storage.put("email_messages", tenant_id, "draft-approved-test", {
            "id": "draft-approved-test", "lead_id": lead_id, "subject": "Subject",
            "body": "Approved content", "status": "draft"})
        email_delivery = AsyncMock(return_value={
            "status": "sent", "sent": True, "event_id": "mock-event"})
        with patch("engine.sales.router_v1.EmailDelivery.deliver", new=email_delivery):
            sent = client.post("/api/v1/email/send", headers=headers, json={
                "message_id": "draft-approved-test", "idempotency_key": "send-approved",
                "consent_confirmed": True})
        self.assertEqual(sent.status_code, 200)
        email_delivery.assert_awaited_once()
        self.assertEqual(storage.get(
            "email_messages", tenant_id, "draft-approved-test")["status"], "sent")

        storage.put("consent_records", tenant_id, lead_id, {
            "contact_id": lead_id, "consented": True, "purpose": "voice_call"})

        class OfficeHours:
            @classmethod
            def now(cls):
                return datetime(2027, 1, 1, 10)

        voice_delivery = AsyncMock(return_value={
            "status": "dry_run", "call_placed": False})
        body = {
            "command": "call software development leads in campaign 123",
            "lead_id": lead_id, "service_id": "software_development",
            "confirmed": True, "consent_confirmed": True, "approved_script": True,
            "idempotency_key": "voice-approved-once",
        }
        with patch("engine.sales.router_v1.datetime", OfficeHours), patch(
                "engine.sales.router_v1.VoiceDelivery.start_call", new=voice_delivery):
            first = client.post("/api/v1/voice/calls", headers=headers, json=body)
            second = client.post("/api/v1/voice/calls", headers=headers, json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        voice_delivery.assert_awaited_once()
        self.assertFalse(first.json()["call_placed"])

    def test_provider_secret_api_encrypts_without_returning_credential(self):
        import engine.main as main

        client = TestClient(main.app)
        tenant_id = "tenant-secret-route"
        headers = {"Authorization": f"Bearer {make_token('ceo@example.test', 'CEO', 4, tenant_id)}"}
        with patch.object(cfg, "KMS_MASTER_KEY", "K" * 48):
            response = client.put("/api/v1/settings/provider-secrets", headers=headers, json={
                "name": "smtp_password", "secret": "not-returned-in-api-response"})
            from engine.db.storage import storage
            saved = storage.get("tenant_secrets", tenant_id, "smtp_password")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["secret_returned"])
        self.assertNotIn("not-returned-in-api-response", response.text)
        self.assertNotIn("not-returned-in-api-response", json.dumps(saved))

    def test_compose_manifest_keeps_provider_effects_opt_in_and_containers_hardened(self):
        compose_path = Path(__file__).resolve().parents[1] / "deploy" / "compose.yaml"
        text = compose_path.read_text(encoding="utf-8")
        self.assertIn('SALES_DRY_RUN: "true"', text)
        self.assertIn('EMAIL_LIVE_ENABLED: "false"', text)
        self.assertIn('VOICE_LIVE_ENABLED: "false"', text)
        self.assertGreaterEqual(text.count("read_only: true"), 4)
        self.assertGreaterEqual(text.count("cap_drop:"), 4)
        self.assertIn("no-new-privileges:true", text)
        self.assertIn("127.0.0.1:8600:8600", text)


if __name__ == "__main__":
    unittest.main()
