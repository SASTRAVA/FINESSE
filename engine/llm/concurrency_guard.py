"""Process-local priority semaphore for scarce local inference capacity."""
from __future__ import annotations

import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager


class PrioritySemaphore:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._active = 0
        self._sequence = itertools.count()
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._lock = asyncio.Lock()

    async def _wake_next(self) -> None:
        while self._active < self.capacity and self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if future.cancelled():
                continue
            self._active += 1
            future.set_result(True)

    @asynccontextmanager
    async def slot(self, priority: int = 2, timeout_s: float = 30.0):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        async with self._lock:
            heapq.heappush(self._waiters, (priority, next(self._sequence), future))
            await self._wake_next()
        try:
            await asyncio.wait_for(future, timeout=timeout_s)
        except BaseException:
            async with self._lock:
                future.cancel()
                await self._wake_next()
            raise
        try:
            yield
        finally:
            async with self._lock:
                self._active = max(0, self._active - 1)
                await self._wake_next()
