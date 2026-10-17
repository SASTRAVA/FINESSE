from __future__ import annotations

import re

_SECRET = re.compile(
    r"(?i)\b(?:nvapi-[A-Za-z0-9_-]{12,}|gsk_[A-Za-z0-9_-]{12,}|"
    r"sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|"
    r"AIza[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"xox[baprs]-[A-Za-z0-9-]{12,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\(?:[^\s\\]+\\)*[^\s\\]*")
_POSIX_PATH = re.compile(r"(?<!\w)/(?:home|Users|mnt|private|var)/[^\s]+")


def sanitize_public_text(text: str) -> str:
    """Remove credentials, contact details, and local paths from public-source text."""
    clean = text or ""
    clean = _PRIVATE_KEY.sub("[REDACTED_PRIVATE_KEY]", clean)
    clean = _SECRET.sub("[REDACTED_SECRET]", clean)
    clean = _EMAIL.sub("[REDACTED_EMAIL]", clean)
    clean = _PHONE.sub("[REDACTED_PHONE]", clean)
    clean = _WINDOWS_PATH.sub("[LOCAL_PATH_REDACTED]", clean)
    return _POSIX_PATH.sub("[LOCAL_PATH_REDACTED]", clean)
