"""
Event bus — the nervous system of the "Jarvis" live view.

Every meaningful thing (agent spawned, agent thinking, agent done, memory
written, pattern learned) is published here. The dashboard subscribes over a
WebSocket and renders the orchestra in real time. Pub/sub is async and fan-out,
so any number of watchers can listen without slowing the workers.
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Event:
    kind: str                 # spawn | think | tool | done | memory | learn | error | system
    actor: str                # agent id / role / "orchestrator"
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    trace: str = ""           # correlation id for one directive run

    def json(self) -> dict:
        return asdict(self)


class EventBus:
    def __init__(self, ring: int = 500):
        self._subs: set[asyncio.Queue] = set()
        self._ring: list[Event] = []
        self._ring_max = ring

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def recent(self, n: int = 100) -> list[dict]:
        return [e.json() for e in self._ring[-n:]]

    async def publish(self, event: Event) -> None:
        self._ring.append(event)
        if len(self._ring) > self._ring_max:
            self._ring = self._ring[-self._ring_max:]
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow watcher: drop rather than block the orchestra

    async def emit(self, kind: str, actor: str, message: str, trace: str = "", **data) -> None:
        await self.publish(Event(kind=kind, actor=actor, message=message, trace=trace, data=data))


bus = EventBus()
