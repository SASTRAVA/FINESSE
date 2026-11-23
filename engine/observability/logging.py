"""Structured JSON logging with key and payload redaction before serialization."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

_SENSITIVE_KEY = re.compile(r"(?i)(authorization|cookie|api.?key|password|token|secret|dek|email|phone)")
_CREDENTIAL = re.compile(r"(?i)\b(?:bearer\s+\S+|(?:nvapi-|gsk_|sk-|ghp_)[A-Za-z0-9_-]{12,})\b")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|password|passwd|api[_-]?key|secret|access[_-]?token)"
    r"\s*[:=]\s*([^\s,;]+)")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d().\-\s]{7,}\d)(?!\w)")


def redact(value: Any, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        result = _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", value)
        result = _CREDENTIAL.sub("[REDACTED_SECRET]", result)
        result = _EMAIL.sub("[REDACTED_EMAIL]", result)
        return _PHONE.sub("[REDACTED_PHONE]", result)
    return value


class RedactingJSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", record.getMessage())
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(), "service": "finesse",
            "env": getattr(record, "env", "unknown"), "event": event,
            "request_id": getattr(record, "request_id", ""),
            "trace_id": getattr(record, "trace_id", ""),
            "span_id": getattr(record, "span_id", ""),
            "tenant_id": getattr(record, "tenant_id", ""),
            "user_id": getattr(record, "user_id", ""),
            "route": getattr(record, "route", ""),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "message": record.getMessage(),
        }
        return json.dumps(redact(payload), ensure_ascii=False, separators=(",", ":"),
                          default=str)


def configure_json_logging() -> None:
    """Use the redacting JSON formatter on configured root handlers."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    for handler in root.handlers:
        handler.setFormatter(RedactingJSONFormatter())
