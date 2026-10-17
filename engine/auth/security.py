"""JWT + password hashing. Thin wrappers so the rest of the code stays clean."""
from __future__ import annotations
import time
import hashlib
import json
import threading
from typing import Optional

import jwt
import bcrypt

from ..config import cfg


class LoginThrottle:
    """Process-local failed-login limits shared by client IP and account."""

    def __init__(self, limit: int = 10, window_s: int = 60):
        self.limit = limit
        self.window_s = window_s
        self._by_ip: dict[str, list[float]] = {}
        self._by_account: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def normalize_account(account: str) -> str:
        return account.strip().casefold()

    def _prune(self, now: float) -> None:
        for attempts in (self._by_ip, self._by_account):
            expired = []
            for key, stamps in attempts.items():
                current = [stamp for stamp in stamps if now - stamp < self.window_s]
                if current:
                    attempts[key] = current
                else:
                    expired.append(key)
            for key in expired:
                del attempts[key]

    def allowed(self, *, ip: str | None = None, account: str | None = None) -> bool:
        now = time.monotonic()
        normalized = self.normalize_account(account) if account else ""
        with self._lock:
            self._prune(now)
            return ((not ip or len(self._by_ip.get(ip, ())) < self.limit)
                    and (not normalized
                         or len(self._by_account.get(normalized, ())) < self.limit))

    def failed(self, *, ip: str | None = None, account: str | None = None) -> None:
        now = time.monotonic()
        normalized = self.normalize_account(account) if account else ""
        with self._lock:
            self._prune(now)
            if ip:
                self._by_ip.setdefault(ip, []).append(now)
            if normalized:
                self._by_account.setdefault(normalized, []).append(now)

    def succeeded(self, *, ip: str | None = None, account: str | None = None) -> None:
        normalized = self.normalize_account(account) if account else ""
        with self._lock:
            if ip:
                self._by_ip.pop(ip, None)
            if normalized:
                self._by_account.pop(normalized, None)


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
