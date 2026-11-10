"""
Event bus — the nervous system of the "Jarvis" live view.

Every meaningful thing (agent spawned, agent thinking, agent done, memory
written, pattern learned) is published here. The dashboard subscribes over a
WebSocket and renders the orchestra in real time. Pub/sub is async and fan-out,
so any number of watchers can listen without slowing the workers.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from ..config import cfg

logger = logging.getLogger(__name__)


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
        self._origin = uuid.uuid4().hex
        self._redis_tasks: dict[asyncio.Queue, asyncio.Task] = {}

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        if cfg.REDIS_URL:
            self._redis_tasks[q] = asyncio.create_task(self._listen_redis(q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)
        task = self._redis_tasks.pop(q, None)
        if task:
            task.cancel()

    async def _listen_redis(self, queue: asyncio.Queue) -> None:
        import redis.asyncio as redis
        client = redis.Redis.from_url(cfg.REDIS_URL, decode_responses=True)
        pubsub = client.pubsub()
        try:
            await pubsub.subscribe("finesse:events:v1")
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                envelope = json.loads(message["data"])
                if envelope.get("origin") == self._origin:
                    continue
                event = Event(**envelope["event"])
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Redis event subscription failed")
        finally:
            await pubsub.aclose()
            await client.aclose()

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
        if cfg.REDIS_URL:
            import redis.asyncio as redis
            client = redis.Redis.from_url(cfg.REDIS_URL, decode_responses=True)
            try:
                await client.publish("finesse:events:v1", json.dumps({
                    "origin": self._origin, "event": event.json(),
                }, separators=(",", ":")))
            except Exception:
                logger.exception("Redis event publish failed; local subscribers remain active")
            finally:
                await client.aclose()

    async def emit(self, kind: str, actor: str, message: str, trace: str = "", **data) -> None:
        await self.publish(Event(kind=kind, actor=actor, message=message, trace=trace, data=data))


bus = EventBus()
