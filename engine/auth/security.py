"""JWT + password hashing. Thin wrappers so the rest of the code stays clean."""
from __future__ import annotations
import time
import hashlib
import json
import secrets
import threading
import re
from collections import defaultdict
from typing import Optional

import jwt
import bcrypt

from ..config import cfg
from ..db.storage import storage


class LoginThrottle:
    """Account/IP sliding-window throttle with an optional Redis shared backend."""

    def __init__(self, limit: int = 5, window_s: int = 900, *,
                 redis_client=None, redis_url: str | None = None):
        self.limit = limit
        self.window_s = window_s
        self._by_ip: dict[str, list[float]] = {}
        self._by_account: dict[str, list[float]] = {}
        self._lockout_until: dict[str, float] = {}
        self._strikes: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._redis = redis_client
        if self._redis is None and (redis_url or cfg.REDIS_URL):
            try:
                import redis
            except ImportError as exc:
                raise RuntimeError("REDIS_URL is set but the redis package is unavailable") from exc
            self._redis = redis.Redis.from_url(redis_url or cfg.REDIS_URL, decode_responses=True)

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

    @staticmethod
    def _account_key(account: str) -> str:
        digest = hashlib.sha256(account.encode("utf-8")).hexdigest()
        return f"rl:login:acct:{digest}"

    @staticmethod
    def _redis_key(kind: str, identity: str) -> str:
        return (LoginThrottle._account_key(identity) if kind == "acct"
                else f"rl:login:ip:{identity}")

    def _redis_allowed(self, ip: str | None, account: str) -> bool:
        now = time.time()
        for kind, identity in (("ip", ip or ""), ("acct", account)):
            if not identity:
                continue
            key = self._redis_key(kind, identity)
            if self._redis.exists(key + ":lock"):
                return False
            self._redis.zremrangebyscore(key, 0, now - self.window_s)
            if self._redis.zcard(key) >= self.limit:
                return False
        return True

    def allowed(self, *, ip: str | None = None, account: str | None = None) -> bool:
        normalized = self.normalize_account(account) if account else ""
        if self._redis is not None:
            return self._redis_allowed(ip, normalized)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if any(self._lockout_until.get(key, 0) > now for key in (ip, normalized) if key):
                return False
            for key in (ip, normalized):
                locked_until = self._lockout_until.get(key) if key else None
                if locked_until is not None and locked_until <= now:
                    self._lockout_until.pop(key, None)
                    self._by_ip.pop(key, None)
                    self._by_account.pop(key, None)
            return ((not ip or len(self._by_ip.get(ip, ())) < self.limit)
                    and (not normalized
                         or len(self._by_account.get(normalized, ())) < self.limit))

    def failed(self, *, ip: str | None = None, account: str | None = None) -> None:
        normalized = self.normalize_account(account) if account else ""
        if self._redis is not None:
            now = time.time()
            for kind, identity in (("ip", ip or ""), ("acct", normalized)):
                if not identity:
                    continue
                key = self._redis_key(kind, identity)
                self._redis.zadd(key, {secrets.token_hex(8): now})
                self._redis.expire(key, self.window_s)
                self._redis.zremrangebyscore(key, 0, now - self.window_s)
                if self._redis.zcard(key) >= self.limit:
                    strikes = self._redis.incr(key + ":strikes")
                    self._redis.expire(key + ":strikes", self.window_s * 4)
                    lockout = min(self.window_s, 30 * (2 ** min(strikes - 1, 5)))
                    self._redis.setex(key + ":lock", lockout, "1")
                    self._redis.delete(key)
            return
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            for key, attempts in ((ip, self._by_ip), (normalized, self._by_account)):
                if not key:
                    continue
                values = attempts.setdefault(key, [])
                values.append(now)
                if len(values) >= self.limit:
                    self._strikes[key] += 1
                    lockout = min(self.window_s, 30 * (2 ** min(self._strikes[key] - 1, 5)))
                    self._lockout_until[key] = now + lockout
                    attempts.pop(key, None)

    def succeeded(self, *, ip: str | None = None, account: str | None = None) -> None:
        normalized = self.normalize_account(account) if account else ""
        if self._redis is not None:
            for kind, identity in (("ip", ip or ""), ("acct", normalized)):
                if identity:
                    key = self._redis_key(kind, identity)
                    self._redis.delete(key, key + ":lock", key + ":strikes")
            return
        with self._lock:
            if ip:
                self._by_ip.pop(ip, None)
                self._lockout_until.pop(ip, None)
                self._strikes.pop(ip, None)
            if normalized:
                self._by_account.pop(normalized, None)
                self._lockout_until.pop(normalized, None)
                self._strikes.pop(normalized, None)


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


def make_token(email: str, role: str, tier: int, tenant_id: str = "default") -> str:
    if not isinstance(tenant_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,127}", tenant_id):
        raise ValueError("tenant_id must use lowercase letters, digits, hyphens, or underscores")
    now = int(time.time())
    payload = {
        "sub": email, "role": role, "tier": tier, "tenant_id": tenant_id,
        "iat": now, "exp": now + cfg.JWT_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return None


def make_gatekeeper_approval(email: str, tool: str, args: dict, *,
                             tenant_id: str = "default", ttl_s: int = 900) -> str:
    """Mint a short-lived, action-bound approval after an authenticated human confirms."""
    if ttl_s < 1 or ttl_s > 900:
        raise ValueError("Gatekeeper approval TTL must be between 1 and 900 seconds")
    now = int(time.time())
    nonce = secrets.token_urlsafe(24)
    args_hash = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    storage.put("gatekeeper_approvals", tenant_id, nonce, {
        "nonce": nonce, "tenant_id": tenant_id, "requester_sub": email,
        "tool_name": tool, "args_sha256": args_hash, "status": "ISSUED",
        "expires_at": now + ttl_s,
    })
    payload = {
        "sub": email, "purpose": "gatekeeper_approval", "tool": tool,
        "args_sha256": args_hash, "tenant_id": tenant_id,
        "nonce": nonce, "iat": now, "exp": now + ttl_s,
    }
    return jwt.encode(payload, cfg.JWT_SECRET, algorithm="HS256")


def verify_gatekeeper_approval(token: str, email: str, tool: str, args: dict, *,
                               tenant_id: str = "default") -> bool:
    try:
        payload = jwt.decode(token, cfg.JWT_SECRET, algorithms=["HS256"])
    except Exception:  # noqa: BLE001
        return False
    expected = hashlib.sha256(
        json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if not (payload.get("purpose") == "gatekeeper_approval"
            and payload.get("sub") == email and payload.get("tool") == tool
            and payload.get("tenant_id", "default") == tenant_id
            and payload.get("args_sha256") == expected):
        return False
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        return False
    return storage.consume_once("gatekeeper_approvals", tenant_id, nonce, {
        "nonce": nonce, "requester_sub": email, "tool_name": tool,
        "args_sha256": expected, "status": "CONSUMED",
    })
