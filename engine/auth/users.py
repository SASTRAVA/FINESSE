"""
User store — JSON-backed (swap for a DB later). Maps employees -> roles -> lanes.

The CEO is bootstrapped from .env as the ONLY L4 admin. Everyone else is created
by the CEO/COO and logs in by their name+role. Usage per employee is tracked here
so you can "map by employee data usage" as requested.
"""
from __future__ import annotations
import json
import logging
import re
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from ..config import cfg, vercel_missing_environment
from .rbac import role_of
from .security import hash_pw, verify_pw

_DB = cfg.DATA / "users.json"
_WEAK_PASSWORDS = {"0000", "changeme", "dev-insecure-change-me", "finesse-ceo-2026"}


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("password must not exceed bcrypt's 72-byte limit")
    if password.strip().casefold() in _WEAK_PASSWORDS:
        raise ValueError("password is a known placeholder and cannot be used")


@dataclass
class User:
    email: str
    name: str
    role: str
    pw_hash: str
    tier: int = 1
    tenant_id: str = "default"
    created: float = field(default_factory=time.time)
    usage: dict = field(default_factory=lambda: {"logins": 0, "directives": 0,
                                                  "injections": 0, "tokens_est": 0})

    def public(self) -> dict:
        d = asdict(self)
        d.pop("pw_hash", None)
        d["lane"] = role_of(self.role).lane
        return d


class UserStore:
    def __init__(self):
        self._users: dict[str, User] = {}
        self.load()
        self._bootstrap_ceo()

    # ---- persistence ----
    def load(self):
        if _DB.exists():
            data = json.loads(_DB.read_text(encoding="utf-8"))
            self._users = {e: User(**u) for e, u in data.items()}

    def save(self):
        _DB.parent.mkdir(parents=True, exist_ok=True)
        _DB.write_text(json.dumps({e: asdict(u) for e, u in self._users.items()},
                                  indent=2), encoding="utf-8")

    def _bootstrap_ceo(self):
        if cfg.IS_VERCEL and vercel_missing_environment():
            logging.getLogger("finesse.startup").error(
                "Vercel setup is incomplete. Set CEO_EMAIL, CEO_PASSWORD "
                "(12+ characters), JWT_SECRET, and KMS_MASTER_KEY (each secret 32+ "
                "characters where applicable) in the "
                "Vercel Project Settings > Environment Variables, then redeploy.")
            return
        if len(cfg.JWT_SECRET) < 32:
            raise RuntimeError("Set JWT_SECRET to a random secret of at least 32 characters.")
        validate_password_strength(cfg.CEO_PASSWORD)
        email = cfg.CEO_EMAIL.lower()
        if email not in self._users:
            self._users[email] = User(
                email=email, name="CEO", role="CEO",
                pw_hash=hash_pw(cfg.CEO_PASSWORD), tier=4)
            self.save()

    # ---- ops ----
    def get(self, email: str) -> Optional[User]:
        return self._users.get(email.lower())

    def create(self, email: str, name: str, role: str, password: str,
               tenant_id: str = "default") -> User:
        validate_password_strength(password)
        tenant_id = tenant_id.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", tenant_id):
            raise ValueError("tenant_id must use lowercase letters, digits, hyphens, or underscores")
        email = email.lower()
        if email in self._users:
            raise ValueError("user exists")
        r = role_of(role)
        if role == "CEO":
            raise ValueError("CEO is a singleton admin and cannot be created")
        u = User(email=email, name=name, role=role, pw_hash=hash_pw(password), tier=r.tier,
                 tenant_id=tenant_id)
        self._users[email] = u
        self.save()
        return u

    def change_password(self, email: str, current_password: str, new_password: str) -> None:
        validate_password_strength(new_password)
        user = self.get(email)
        if user is None or not verify_pw(current_password, user.pw_hash):
            raise ValueError("current password is incorrect")
        user.pw_hash = hash_pw(new_password)
        self.save()

    def authenticate(self, email: str, password: str) -> Optional[User]:
        u = self.get(email)
        if u and verify_pw(password, u.pw_hash):
            u.usage["logins"] += 1
            self.save()
            return u
        return None

    def bump(self, email: str, key: str, n: int = 1):
        u = self.get(email)
        if u:
            u.usage[key] = u.usage.get(key, 0) + n
            self.save()

    def all_public(self, tenant_id: str | None = None) -> list[dict]:
        return [u.public() for u in self._users.values()
                if tenant_id is None or u.tenant_id == tenant_id]


users = UserStore()
