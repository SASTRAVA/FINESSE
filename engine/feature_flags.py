"""Tenant-aware persisted kill switches. Missing flags retain backward-compatible defaults."""
from __future__ import annotations

import time

from .audit.pg_audit import audit_log
from .db.storage import storage


class KillSwitches:
    def __init__(self, repository=storage):
        self.repository = repository

    def enabled(self, key: str, tenant_id: str = "default", *, default: bool = True) -> bool:
        for scope in (tenant_id, "__global__"):
            record = self.repository.get("feature_kill_switches", scope, key)
            if record is not None:
                return bool(record.get("enabled", False))
        return default

    def set(self, key: str, enabled: bool, *, tenant_id: str = "__global__",
            actor: str, reason: str) -> dict:
        if not key or not actor or not reason.strip():
            raise ValueError("flag, actor, and reason are required")
        record = {"key": key, "enabled": bool(enabled), "updated_by": actor,
                  "reason": reason[:1000], "updated_at": time.time()}
        self.repository.put("feature_kill_switches", tenant_id, key, record)
        audit_log.append(tenant_id, {"event": "feature_kill_switch.updated", "flag": key,
                                     "enabled": bool(enabled), "actor": actor,
                                     "reason": reason[:1000]})
        return record


kill_switches = KillSwitches()
