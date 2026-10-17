"""Opt-in sales provider adapters. No live effects occur without explicit flags."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from ..config import cfg
from ..db.storage import PlatformStorage, storage
from ..db.tenant_secrets import TenantSecretStore
from ..network_safety import validate_public_target_url


class ProviderPolicyError(RuntimeError):
    pass


def _safe_hmac_secret(secret: str) -> bool:
    normalized = secret.casefold()
    return (len(secret.encode("utf-8")) >= 32 and "<" not in secret and ">" not in secret
            and "generate" not in normalized and "changeme" not in normalized)


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    if not _safe_hmac_secret(secret) or not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature[7:])


def build_voice_callback_url(url: str, *, tenant_id: str, suffix: str = "",
                             contact_id: str = "") -> str:
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("tenant_id", tenant_id))
    if contact_id:
        query.append(("contact_id", contact_id))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") + suffix,
                       urlencode(query), parts.fragment))


def verify_twilio_signature(url: str, parameters: list[tuple[str, str]],
                            signature: str, auth_token: str) -> bool:
    if not signature or not auth_token:
        return False
    material = url
    grouped: dict[str, list[str]] = {}
    for name, value in parameters:
        grouped.setdefault(name, []).append(value)
    for name in sorted(grouped):
        for value in sorted(grouped[name]):
            material += name + value
    expected = base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), material.encode("utf-8"),
                 hashlib.sha1).digest()).decode("ascii")
    return hmac.compare_digest(expected, signature)


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:nvapi-[A-Za-z0-9_-]{12,}|gsk_[A-Za-z0-9_-]{12,}|"
               r"sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,})\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")


def scrub_provider_text(text: str, *, redact_pii: bool | None = None) -> str:
    clean = text
    for pattern in _SECRET_PATTERNS:
        clean = pattern.sub("[REDACTED]", clean)
    if cfg.REDACT_PII_ON_EXTERNAL_LLM if redact_pii is None else redact_pii:
        clean = _EMAIL.sub("[REDACTED_EMAIL]", clean)
        clean = _PHONE.sub("[REDACTED_PHONE]", clean)
    return clean


def scrub_external_secrets(value):
    if isinstance(value, str):
        return scrub_provider_text(value, redact_pii=False)
    if isinstance(value, list):
        return [scrub_external_secrets(item) for item in value]
    if isinstance(value, dict):
        return {str(key): scrub_external_secrets(item) for key, item in value.items()}
    return value


def _public_https_url(url: str) -> str:
    if not url:
        raise ProviderPolicyError("provider URL is not configured")
    try:
        validate_public_target_url(url)
    except ValueError as exc:
        raise ProviderPolicyError("provider URL must resolve to a public target") from exc
    if urlsplit(url).scheme != "https" or urlsplit(url).fragment:
        raise ProviderPolicyError("live providers require HTTPS")
    return url


class EmailDelivery:
    def __init__(self, repository: PlatformStorage = storage,
                 http_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient):
        self.repository = repository
        self.http_client_factory = http_client_factory

    async def deliver(self, *, tenant_id: str, message_id: str, recipient: str,
                      subject: str, body: str, idempotency_key: str,
                      unsubscribe_url: str) -> dict:
        address = parseaddr(recipient)[1]
        if not address or address != recipient or "@" not in address:
            raise ProviderPolicyError("recipient address is invalid")
        if not idempotency_key or len(idempotency_key) > 200:
            raise ProviderPolicyError("a bounded idempotency key is required")
        if cfg.SALES_DRY_RUN or not cfg.SALES_LIVE_OUTREACH_ENABLED or not cfg.EMAIL_LIVE_ENABLED:
            return {"status": "dry_run", "sent": False}
        if cfg.EMAIL_PROVIDER not in {"smtp", "webhook"}:
            raise ProviderPolicyError("EMAIL_PROVIDER must be smtp or webhook for live delivery")
        unsubscribe_url = _public_https_url(unsubscribe_url)

        event_key = "outbound:" + hashlib.sha256(
            f"{tenant_id}:{idempotency_key}".encode("utf-8")).hexdigest()
        if not self.repository.put_if_absent("email_events", tenant_id, event_key, {
                "id": event_key, "message_id": message_id, "event": "delivery_reserved"}):
            previous = self.repository.get("email_events", tenant_id, event_key)
            if previous and previous.get("message_id") == message_id and previous.get("event") == "sent":
                return {"status": "sent", "sent": True, "event_id": event_key}
            raise ProviderPolicyError(
                "delivery attempt is already reserved; reconcile provider status before retrying")
        clean_subject = scrub_provider_text(subject)
        clean_body = scrub_provider_text(body)
        if cfg.EMAIL_PROVIDER == "smtp":
            smtp_password = TenantSecretStore(self.repository).get(
                tenant_id, "smtp_password") or cfg.SMTP_PASSWORD
            if not all((cfg.SMTP_HOST, cfg.SMTP_USERNAME, smtp_password, cfg.SMTP_FROM)):
                raise ProviderPolicyError("SMTP host, credentials, and sender must be configured")
            message = EmailMessage()
            message["From"] = cfg.SMTP_FROM
            message["To"] = address
            message["Subject"] = clean_subject
            message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            message.set_content(clean_body)
            await asyncio.to_thread(self._smtp_send, message, smtp_password)
        else:
            url = _public_https_url(cfg.EMAIL_WEBHOOK_URL)
            webhook_token = TenantSecretStore(self.repository).get(
                tenant_id, "email_webhook_token") or cfg.EMAIL_WEBHOOK_TOKEN
            if not webhook_token:
                raise ProviderPolicyError("EMAIL_WEBHOOK_TOKEN must be configured")
            async with self.http_client_factory(timeout=10.0) as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {webhook_token}",
                                  "Idempotency-Key": event_key},
                    json={"from": cfg.SMTP_FROM, "to": address,
                          "subject": clean_subject, "text": clean_body,
                          "list_unsubscribe": unsubscribe_url})
                response.raise_for_status()
        self.repository.put("email_events", tenant_id, event_key,
                            {"id": event_key, "message_id": message_id, "event": "sent"})
        return {"status": "sent", "sent": True, "event_id": event_key}

    @staticmethod
    def _smtp_send(message: EmailMessage, password: str) -> None:
        with smtplib.SMTP(cfg.SMTP_HOST, cfg.SMTP_PORT, timeout=10) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(cfg.SMTP_USERNAME, password)
            server.send_message(message)


class VoiceDelivery:
    def __init__(self, http_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient):
        self.http_client_factory = http_client_factory

    async def start_call(self, *, tenant_id: str, contact_id: str, to: str,
                         script: str, authorization_verified: bool) -> dict:
        if not authorization_verified:
            raise ProviderPolicyError("verified single-use command authorization is required")
        if cfg.SALES_DRY_RUN or not cfg.SALES_LIVE_OUTREACH_ENABLED or not cfg.VOICE_LIVE_ENABLED:
            return {"status": "dry_run", "call_placed": False}
        if cfg.VOICE_PROVIDER != "twilio":
            raise ProviderPolicyError("VOICE_PROVIDER must be twilio for live calling")
        secret_store = TenantSecretStore()
        account_sid = secret_store.get(tenant_id, "twilio_account_sid")
        auth_token = secret_store.get(tenant_id, "twilio_auth_token")
        caller_id = secret_store.get(tenant_id, "twilio_caller_id")
        if tenant_id == "default":
            account_sid = account_sid or cfg.TWILIO_ACCOUNT_SID
            auth_token = auth_token or cfg.TWILIO_AUTH_TOKEN
            caller_id = caller_id or cfg.TWILIO_CALLER_ID
        if not all((account_sid, auth_token, caller_id)):
            raise ProviderPolicyError("Twilio account, token, and caller ID must be configured")
        webhook_url = _public_https_url(cfg.VOICE_WEBHOOK_URL)
        if not re.fullmatch(r"\+[1-9]\d{7,14}", to):
            raise ProviderPolicyError("destination must be an E.164 number")
        callback_url = build_voice_callback_url(webhook_url, tenant_id=tenant_id)
        opt_out_url = build_voice_callback_url(
            webhook_url, tenant_id=tenant_id, contact_id=contact_id,
            suffix="/opt-out")
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
        _public_https_url(url)
        spoken_script = scrub_provider_text(script) + " Say stop or press 9 to opt out."
        twiml = (
            "<Response><Gather input=\"speech dtmf\" method=\"POST\" timeout=\"7\" "
            f"action=\"{html.escape(opt_out_url, quote=True)}\">"
            f"<Say>{html.escape(spoken_script)}</Say></Gather>"
            "<Say>We did not receive a response. Goodbye.</Say></Response>")
        async with self.http_client_factory(timeout=10.0) as client:
            response = await client.post(
                url, auth=(account_sid, auth_token),
                data={"To": to, "From": caller_id, "Twiml": twiml,
                      "StatusCallback": callback_url})
            response.raise_for_status()
            payload = response.json()
        return {"status": "queued", "call_placed": True, "provider_id": payload.get("sid")}


class LeadEnrichment:
    def __init__(self, http_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient):
        self.http_client_factory = http_client_factory

    async def enrich(self, company_domain: str, *, tenant_id: str) -> dict:
        if not cfg.SALES_ENRICHMENT_ENABLED:
            return {"status": "dry_run", "enriched": False}
        url = _public_https_url(cfg.ENRICHMENT_PROVIDER_URL)
        token = TenantSecretStore().get(
            tenant_id, "enrichment_api_token") or cfg.ENRICHMENT_API_TOKEN
        if not token:
            raise ProviderPolicyError("ENRICHMENT_API_TOKEN must be configured")
        if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9.-]+", company_domain):
            raise ProviderPolicyError("company_domain is invalid")
        async with self.http_client_factory(timeout=10.0) as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {token}"},
                json={"domain": company_domain})
            response.raise_for_status()
            data = response.json()
        return {"status": "enriched", "enriched": True, "data": data}


class CalendarSync:
    def __init__(self, http_client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient):
        self.http_client_factory = http_client_factory

    async def sync(self, meeting: dict, *, tenant_id: str, idempotency_key: str) -> dict:
        if not cfg.CALENDAR_SYNC_ENABLED or cfg.CALENDAR_PROVIDER == "local":
            return {"status": "local_only", "synced": False}
        token = TenantSecretStore().get(
            tenant_id, "calendar_api_token") or cfg.CALENDAR_API_TOKEN
        if cfg.CALENDAR_PROVIDER != "webhook" or not token:
            raise ProviderPolicyError("calendar webhook provider and token are required")
        url = _public_https_url(cfg.CALENDAR_WEBHOOK_URL)
        async with self.http_client_factory(timeout=10.0) as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {token}",
                              "Idempotency-Key": idempotency_key},
                json=meeting)
            response.raise_for_status()
        return {"status": "synced", "synced": True}


def create_calendar_invite(*, uid: str, subject: str, start: str, end: str,
                           organizer: str, attendee: str) -> str:
    from datetime import datetime, timezone

    def parse(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("calendar datetimes must include a timezone")
        return parsed.astimezone(timezone.utc)

    starts, ends = parse(start), parse(end)
    if ends <= starts:
        raise ValueError("meeting end must occur after meeting start")
    if (len(organizer) > 254 or len(attendee) > 254
            or not _EMAIL.fullmatch(organizer) or not _EMAIL.fullmatch(attendee)):
        raise ValueError("organizer and attendee must be email addresses")

    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")

    fmt = "%Y%m%dT%H%M%SZ"
    lines = (
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FINESSE//Calendar//EN",
        "METHOD:REQUEST", "BEGIN:VEVENT", f"UID:{escape(uid)}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{starts.strftime(fmt)}", f"DTEND:{ends.strftime(fmt)}",
        f"SUMMARY:{escape(subject)}", f"ORGANIZER:mailto:{organizer}",
        f"ATTENDEE;RSVP=TRUE:mailto:{attendee}", "END:VEVENT", "END:VCALENDAR")
    folded = []
    for line in lines:
        current = ""
        for char in line:
            if len((current + char).encode("utf-8")) > 75:
                folded.append(current)
                current = " " + char
            else:
                current += char
        folded.append(current)
    return "\r\n".join((*folded, ""))
