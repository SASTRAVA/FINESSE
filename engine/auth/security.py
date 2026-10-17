"""JWT + password hashing. Thin wrappers so the rest of the code stays clean."""
from __future__ import annotations
import time
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
