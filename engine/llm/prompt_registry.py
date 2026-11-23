"""Immutable, tenant-aware prompt versions with explicit activation and rollback."""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..db.storage import storage

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
GLOBAL_TENANT = "__global__"


@dataclass(frozen=True)
class PromptVersion:
    tenant_id: str
    agent_id: str
    version_semver: str
    system_prompt: str
    template_hash: str
    output_schema_version: str = "1"
    status: str = "DRAFT"


class PromptRegistry:
    def __init__(self, repository=storage):
        self.repository = repository

    def register(self, agent_id: str, version: str, system_prompt: str, *,
                 tenant_id: str = GLOBAL_TENANT, output_schema_version: str = "1",
                 created_by: str = "system") -> PromptVersion:
        if not agent_id or not system_prompt.strip() or not _SEMVER.fullmatch(version):
            raise ValueError("agent_id, non-empty prompt, and semantic version are required")
        digest = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        key = f"{agent_id}:{version}"
        prior = self.repository.get("prompt_templates", tenant_id, key)
        if prior:
            if prior.get("template_hash") != digest:
                raise ValueError("prompt versions are immutable")
            return PromptVersion(**{k: prior[k] for k in PromptVersion.__dataclass_fields__})
        record = PromptVersion(tenant_id, agent_id, version, system_prompt, digest,
                               output_schema_version)
        value = {**record.__dict__, "created_by": created_by, "created_at": time.time()}
        self.repository.put("prompt_templates", tenant_id, key, value)
        return record

    def activate(self, agent_id: str, version: str, *, tenant_id: str = GLOBAL_TENANT) -> None:
        key = f"{agent_id}:{version}"
        record = self.repository.get("prompt_templates", tenant_id, key)
        if not record:
            raise KeyError(key)
        for record_id, current in self.repository.list_items("prompt_templates", tenant_id):
            if current.get("agent_id") == agent_id and current.get("status") == "ACTIVE":
                current["status"] = "DEPRECATED"
                self.repository.put("prompt_templates", tenant_id, record_id, current)
        record["status"] = "ACTIVE"
        self.repository.put("prompt_templates", tenant_id, key, record)

    def resolve(self, agent_id: str, *, tenant_id: str = "default") -> PromptVersion | None:
        for scope in (tenant_id, GLOBAL_TENANT):
            records = [value for _, value in self.repository.list_items(
                "prompt_templates", scope) if value.get("agent_id") == agent_id
                and value.get("status") == "ACTIVE"]
            if records:
                record = max(records, key=lambda item: tuple(map(int, item["version_semver"].split("."))))
                return PromptVersion(**{k: record[k] for k in PromptVersion.__dataclass_fields__})
        return None

    def load_fixtures(self, directory: Path | None = None) -> int:
        """Install checked-in JSON-compatible YAML defaults without overwriting tenant data."""
        directory = directory or Path(__file__).resolve().parents[1] / "agents" / "prompts"
        loaded = 0
        if not directory.exists():
            return loaded
        for path in sorted(directory.glob("*.yaml")):
            fixture = json.loads(path.read_text(encoding="utf-8"))
            agent_id, version = fixture["agent_id"], fixture["version_semver"]
            existing = self.repository.get("prompt_templates", GLOBAL_TENANT,
                                           f"{agent_id}:{version}")
            if existing is None:
                self.register(agent_id, version, fixture["system_prompt"],
                              tenant_id=GLOBAL_TENANT,
                              output_schema_version=fixture.get("output_schema_version", "1"),
                              created_by="builtin-fixture")
                loaded += 1
            if fixture.get("status") == "ACTIVE" and self.resolve(agent_id) is None:
                self.activate(agent_id, version, tenant_id=GLOBAL_TENANT)
        return loaded


prompt_registry = PromptRegistry()
prompt_registry.load_fixtures()
