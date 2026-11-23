"""Slack request signature verification over exact raw request bytes."""
from __future__ import annotations

import hashlib
import hmac
import time


def verify_slack_signature(raw_body: bytes, timestamp: str, signature: str,
                           signing_secret: str, *, now: float | None = None) -> bool:
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        parsed_timestamp = int(timestamp)
    except ValueError:
        return False
    if abs((time.time() if now is None else now) - parsed_timestamp) > 300:
        return False
    base = b"v0:" + timestamp.encode("ascii") + b":" + raw_body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
