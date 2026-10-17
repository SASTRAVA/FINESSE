"""Synchronous redaction for security findings before persistence or export."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Mapping

_PROCESS_SALT = os.urandom(32)
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:nvapi-[A-Za-z0-9_-]{16,}|gsk_[A-Za-z0-9_-]{16,}|"
               r"sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
)
_SENSITIVE_KEY = re.compile(r"(?i)(?:secret|token|password|credential|authorization|"
                            r"private.?key|api.?key|raw.?record|match)")
_PRESERVED = {"file", "filepath", "path", "line", "line_number", "rule_id", "rule"}


def _redact_string(value: str, salt: bytes) -> str:
    def replace(match: re.Match) -> str:
        digest = hmac.new(salt, match.group(0).encode("utf-8"), hashlib.sha256).hexdigest()[:8]
        return f"<REDACTED_SECRET:{digest}>"
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(replace, value)
    return value


def redact_raw_record(record: Mapping, *, salt: bytes | None = None) -> dict:
    """Redact secrets recursively while preserving finding location and rule metadata."""
    if not isinstance(record, Mapping):
        raise TypeError("security finding must be a mapping")
    key = salt or _PROCESS_SALT
    output: dict = {}

    def clean(value, field_name: str = ""):
        if field_name.casefold() in _PRESERVED:
            return value
        if _SENSITIVE_KEY.search(field_name):
            if isinstance(value, str) and value:
                digest = hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
                return f"<REDACTED_SECRET:{digest}>"
            if isinstance(value, (dict, list, tuple)):
                raw = repr(value)
                digest = hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
                return f"<REDACTED_SECRET:{digest}>"
        if isinstance(value, str):
            return _redact_string(value, key)
        if isinstance(value, Mapping):
            return {str(k): clean(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(item, field_name) for item in value]
        if isinstance(value, tuple):
            return [clean(item, field_name) for item in value]
        return value

    output.update({str(k): clean(v, str(k)) for k, v in record.items()})
    fingerprint_material = "|".join(str(output.get(key_name, "")) for key_name in
                                    ("rule_id", "rule", "file", "path", "line"))
    output["dedup_fingerprint"] = hmac.new(
        key, fingerprint_material.encode("utf-8"), hashlib.sha256).hexdigest()
    return output
