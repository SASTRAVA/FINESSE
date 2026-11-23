"""Fail-closed optional runtime gate for signed portable deployments."""
from __future__ import annotations

import json
from pathlib import Path

from .signatures import SignatureVerificationError, verify_license


def validate_portable_license(*, required: bool, license_file: str | Path,
                              public_key: str, tenant_id: str,
                              now: int | None = None) -> dict | None:
    """Validate a signed license and its tenant; disabled only for unlicensed builds."""
    if not required:
        return None
    if not public_key.strip() or not tenant_id.strip():
        raise SignatureVerificationError(
            "portable license trust key or tenant identity is not configured")
    try:
        path = Path(license_file)
        if path.stat().st_size > 64 * 1024:
            raise SignatureVerificationError("portable license document exceeds the size limit")
        document = json.loads(path.read_text(encoding="utf-8"))
    except SignatureVerificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SignatureVerificationError("portable license document is unavailable or invalid") from exc
    claims = verify_license(document, public_key, now=now)
    if claims["tenant_id"] != tenant_id:
        raise SignatureVerificationError("portable license tenant does not match this installation")
    return claims
