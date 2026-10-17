"""
Agent registry — the living catalogue of agent types.

Two powers you asked for:
  1. SPAWN SWARMS: `spawn(key)` mints a brand-new Agent instance every time,
     so each input can raise its own swarm of fresh workers (cheap: see base.py).
  2. GROW NEW AGENTS FROM DATA: `register_from_injection(...)` turns an injected
     requirement/prompt/pdf into a NEW agent type on the fly — "swarms of new
     agents joining each time we give it input." New specs are also mirrored to
     the Obsidian vault (04_AI_Agents) so the graph shows the org growing.
"""
from __future__ import annotations
import re
from pathlib import Path

from ..config import cfg
from .base_types import AgentSpec
from .base import Agent

_VAULT_AGENTS = cfg.VAULT / "04_AI_Agents" / "_Generated"


class Registry:
    def __init__(self):
        self._specs: dict[str, AgentSpec] = {}

    # ---- registration ----
    def register(self, spec: AgentSpec, mirror: bool = False) -> AgentSpec:
        self._specs[spec.key] = spec
        if mirror:
            self._mirror(spec)
        return spec

    def get(self, key: str) -> AgentSpec | None:
        return self._specs.get(key)

    def all(self) -> list[AgentSpec]:
        return list(self._specs.values())

    def by_lane(self, lane: str) -> list[AgentSpec]:
        return [s for s in self._specs.values() if s.lane == lane]

    # ---- spawning ----
    def spawn(self, key: str, trace: str = "") -> Agent:
        spec = self._specs.get(key)
        if spec is None:
            raise KeyError(f"unknown agent type: {key}")
        return Agent(spec, trace=trace)

    def spawn_swarm(self, keys: list[str], trace: str = "") -> list[Agent]:
        """Cap the swarm size so 30 users can't blow past SWARM_MAX_AGENTS."""
        keys = keys[: cfg.SWARM_MAX_AGENTS]
        return [self.spawn(k, trace=trace) for k in keys]

    # ---- growth from injected data ----
    def register_from_injection(self, *, title: str, lane: str, mandate: str,
                                model_role: str = "fast") -> AgentSpec:
        key = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "custom_agent"
        if key in self._specs:
            key = f"{key}_{len(self._specs)}"
        spec = AgentSpec(
            key=key, title=title.strip().title() + " Agent", lane=lane,
            model_role=model_role,
            system_prompt=(f"You are the {title.title()} Agent for Sastrava, operating in the "
                           f"{lane} lane. Mandate:\n{mandate}\n\nUse retrieved brain context. "
                           f"Never fully automate a human out — surface decisions for review."),
        )
        self.register(spec, mirror=True)
        self._persist(spec)          # survive restarts (was lost before)
        return spec

    # ---- persistence: generated agents survive restarts ----
    def _persist(self, spec: AgentSpec) -> None:
        import json
        from dataclasses import asdict
        try:
            store = cfg.DATA / "agents.json"
            data = json.loads(store.read_text(encoding="utf-8")) if store.exists() else []
            if any(d.get("key") == spec.key for d in data):
                return
            data.append(asdict(spec))
            store.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[registry] persist failed: {e}")

    def load_persisted(self) -> int:
        """Re-register generated agents saved from prior sessions. Call on startup."""
        import json
        try:
            store = cfg.DATA / "agents.json"
            if not store.exists():
                return 0
            n = 0
            for d in json.loads(store.read_text(encoding="utf-8")):
                if d.get("key") and d["key"] not in self._specs:
                    self.register(AgentSpec(**d))
                    n += 1
            return n
        except Exception as e:  # noqa: BLE001
            print(f"[registry] load_persisted failed: {e}")
            return 0

    def _mirror(self, spec: AgentSpec) -> None:
        try:
            _VAULT_AGENTS.mkdir(parents=True, exist_ok=True)
            note = _VAULT_AGENTS / f"{spec.title.replace(' ', '_')}.md"
            note.write_text(
                f"---\ntitle: {spec.title}\nlane: {spec.lane}\nmodel_role: {spec.model_role}\n"
                f"tags: [agent, generated, {spec.lane}]\n---\n\n"
                f"# {spec.title}\n\n**Lane:** {spec.lane}\n\n## System Prompt\n\n"
                f"```\n{spec.system_prompt}\n```\n",
                encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[registry] mirror failed: {e}")


registry = Registry()
