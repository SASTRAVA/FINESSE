import hashlib
import hmac
import time

import pytest

from engine.approvals.channels.email import confirm_approval, view_approval
from engine.approvals.channels.slack import verify_slack_signature
from engine.mcp.manifest_guard import ManifestRejected, PinnedManifest
from engine.network_safety import validate_public_target_url
from engine.webhooks.dispatcher import sign_delivery, verify_delivery


def test_slack_signature_uses_exact_body_and_rejects_replay():
    secret, raw, timestamp = "test-signing-secret", b'{"x":1}', str(int(time.time()))
    signature = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + raw,
                                 hashlib.sha256).hexdigest()
    assert verify_slack_signature(raw, timestamp, signature, secret)
    assert not verify_slack_signature(raw + b" ", timestamp, signature, secret)
    assert not verify_slack_signature(raw, "1", signature, secret, now=time.time())


def test_email_get_never_confirms_and_explicit_post_required():
    view = view_approval("id-1", {"tool": "send"}, "hash", "PENDING")
    assert view.status == "PENDING"
    with pytest.raises(ValueError):
        confirm_approval(method="GET", authenticated=True, explicit_confirmation=True,
                         approve_callback=lambda _: "approved", approval_id="id-1")
    with pytest.raises(PermissionError):
        confirm_approval(method="POST", authenticated=False, explicit_confirmation=True,
                         approve_callback=lambda _: "approved", approval_id="id-1")


def test_pinned_mcp_manifest_fails_closed_on_drift_and_sensitive_egress():
    guard = PinnedManifest()
    tools = [{"name": "read", "schema": {"type": "object"}}]
    guard.approve("tenant", "server", tools)
    guard.verify("tenant", "server", tools, sensitivity="internal")
    with pytest.raises(ManifestRejected):
        guard.verify("tenant", "server", tools + [{"name": "write"}], sensitivity="internal")
    with pytest.raises(ManifestRejected):
        guard.verify("tenant", "server", tools, sensitivity="confidential")


def test_outbound_signature_round_trip_and_ssrf_block():
    raw = b'{"event":"test"}'
    headers = sign_delivery(raw, "unit-test-secret", timestamp=100, delivery_id="test-id")
    assert verify_delivery(raw, "unit-test-secret", headers["X-Finesse-Timestamp"],
                           headers["X-Finesse-Signature"], now=100)
    assert not verify_delivery(raw + b"x", "unit-test-secret", headers["X-Finesse-Timestamp"],
                               headers["X-Finesse-Signature"], now=100)
    with pytest.raises(ValueError, match="non-public"):
        validate_public_target_url("http://169.254.169.254/latest/meta-data")
