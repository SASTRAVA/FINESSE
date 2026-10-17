"""JWT + password hashing. Thin wrappers so the rest of the code stays clean."""
from __future__ import annotations
import time
import hashlib
import json
from typing import Optional

import jwt
import bcrypt

from ..config import cfg


def _b(pw: str) -> bytes:
    # bcrypt hard-limits secrets to 72 bytes; truncate deterministically.
    return pw.encode("utf-8")[:72]


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(_b(pw), bcrypt.gensalt()).decode("utf-8")


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_b(pw), hashed.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def make_token(email: str, role: str, tier: int) -> str:
    now = int(time.time())
    payload = {
        "sub": email, "role": role, "tier": tier,
        "iat": now, "exp": now + cfg.JWT_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None


def make_gatekeeper_approval(email: str, tool: str, args: dict) -> str:
    """Mint a short-lived, action-bound approval after an authenticated human confirms."""
    now = int(time.time())
    payload = {
        "sub": email, "purpose": "gatekeeper_approval", "tool": tool,
        "args_sha256": hashlib.sha256(
            json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "iat": now, "exp": now + 120,
    }
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def verify_gatekeeper_approval(token: str, email: str, tool: str, args: dict) -> bool:
    try:
        payload = jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return False
    expected = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return (payload.get("purpose") == "gatekeeper_approval"
            and payload.get("sub") == email and payload.get("tool") == tool
            and payload.get("args_sha256") == expected)
