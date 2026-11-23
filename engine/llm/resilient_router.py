"""Async circuit-breaker primitives and sovereignty-safe provider selection."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class _Circuit:
    failures: int = 0
    opened_at: float = 0.0
    probe: bool = False


class CircuitOpen(RuntimeError):
    pass


class CircuitBreakers:
    def __init__(self, *, threshold: int = 3, cooldown_s: float = 30.0):
        self.threshold, self.cooldown_s = threshold, cooldown_s
        self._states: dict[str, _Circuit] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def acquire(self, provider: str) -> None:
        lock = self._locks.setdefault(provider, asyncio.Lock())
        async with lock:
            state = self._states.setdefault(provider, _Circuit())
            if not state.opened_at:
                return
            if time.monotonic() - state.opened_at < self.cooldown_s or state.probe:
                raise CircuitOpen(provider)
            state.probe = True

    async def success(self, provider: str) -> None:
        async with self._locks.setdefault(provider, asyncio.Lock()):
            self._states[provider] = _Circuit()

    async def failure(self, provider: str) -> None:
        async with self._locks.setdefault(provider, asyncio.Lock()):
            state = self._states.setdefault(provider, _Circuit())
            state.failures += 1
            state.probe = False
            if state.failures >= self.threshold:
                state.opened_at = time.monotonic()

    async def call(self, provider: str, operation):
        await self.acquire(provider)
        try:
            result = await operation()
        except Exception:
            await self.failure(provider)
            raise
        await self.success(provider)
        return result


def eligible_pool(sensitivity: str, *, local_available: bool, cloud_available: bool) -> tuple[str, ...]:
    if sensitivity not in {"public", "internal", "confidential", "restricted"}:
        raise ValueError("unsupported sensitivity")
    if sensitivity in {"confidential", "restricted"}:
        return ("local",) if local_available else ()
    pool = tuple(name for name, enabled in (("nim", cloud_available), ("groq", cloud_available),
                                             ("local", local_available)) if enabled)
    return pool
