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


@dataclass
class Session:
    id: str
    kind: str                       # "swarm" | "single"
    prompt: str
    trace: str
    requested_by: str = ""
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

    def start(self, kind: str, prompt: str, trace: str, requested_by: str = "") -> Session:
        s = Session(id=uuid.uuid4().hex[:8], kind=kind, prompt=prompt, trace=trace,
                    requested_by=requested_by)
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

    def list(self, limit: int = 40) -> list[dict]:
        return [s.json() for s in reversed(self._list[-limit:])]

    def active(self) -> int:
        return sum(1 for s in self._list if s.status == "running")


sessions = SessionRegistry()
