"""
Swarm sessions — a live registry of every run so the UI can show swarms as
first-class things: one per prompt (a swarm) or a single-agent run.

In-memory ring (single process). Each new prompt gets its own session id, so the
Swarms tab literally shows "a new swarm per prompt". Statuses flip running->done
so another tab polling /api/swarms sees them live.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field, asdict
from ..auth.rbac import role_of


@dataclass
class Session:
    id: str
    kind: str                       # "swarm" | "single"
    prompt: str
    trace: str
    requested_by: str = ""
    owner: str = ""
    lane: str = "general"
    tenant_id: str = "default"
    status: str = "running"         # running | done | error
    agents: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    ts: float = field(default_factory=time.time)
    preview: str = ""

    def json(self) -> dict:
        d = asdict(self)
        d["prompt"] = self.prompt[:160]
        return d


class SessionRegistry:
    def __init__(self, ring: int = 60):
        self._ring = ring
        self._list: list[Session] = []

    def start(self, kind: str, prompt: str, trace: str, requested_by: str = "",
              owner: str = "", lane: str = "general",
              tenant_id: str = "default") -> Session:
        s = Session(id=uuid.uuid4().hex[:8], kind=kind, prompt=prompt, trace=trace,
                    requested_by=requested_by, owner=owner, lane=lane,
                    tenant_id=tenant_id)
        self._list.append(s)
        if len(self._list) > self._ring:
            self._list = self._list[-self._ring:]
        return s

    def finish(self, s: Session, *, agents: list[str], elapsed: float, preview: str,
               status: str = "done"):
        s.agents = agents
        s.elapsed = round(elapsed, 2)
        s.preview = preview[:240]
        s.status = status

    def list(self, limit: int = 40, *, user_id: str = "", user_role: str = "",
             tenant_id: str = "default") -> list[dict]:
        visible = self._visible(user_id, user_role, tenant_id)
        return [s.json() for s in reversed(visible[-limit:])]

    def active(self, *, user_id: str = "", user_role: str = "",
               tenant_id: str = "default") -> int:
        return sum(1 for s in self._visible(user_id, user_role, tenant_id)
                   if s.status == "running")

    def _visible(self, user_id: str, user_role: str, tenant_id: str) -> list[Session]:
        tenant_sessions = [session for session in self._list
                           if session.tenant_id == tenant_id]
        if role_of(user_role).tier >= 3:
            return tenant_sessions
        return [session for session in tenant_sessions if session.owner == user_id]


sessions = SessionRegistry()
