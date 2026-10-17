"""
TurboQuant — the latency layer that keeps swarms fast under load.

Quantization proper happens in the *models*:
  - embeddings: fastembed serves INT8 ONNX (see rag/embeddings.py)
  - LLMs (later): local vLLM/TensorRT-LLM AWQ/FP8 (see LOCAL_LLM_* in .env)

TurboQuant is the *serving* half of "turbo": it makes sure 30 users x a swarm
of agents never stampede the (rate-limited, free-tier) inference endpoint:

  1. global concurrency semaphore  -> bounded in-flight calls
  2. semantic-ish response cache    -> identical (model, prompt) served from RAM
  3. dedup of in-flight identical calls (single-flight)

All async, so nothing blocks the event loop.
"""
from __future__ import annotations
import asyncio
import hashlib
from collections import OrderedDict
from typing import Awaitable, Callable

from ..config import cfg


class _LRU:
    def __init__(self, size: int):
        self.size = size
        self._d: "OrderedDict[str, str]" = OrderedDict()

    def get(self, k: str):
        if k in self._d:
            self._d.move_to_end(k)
            return self._d[k]
        return None

    def put(self, k: str, v: str):
        self._d[k] = v
        self._d.move_to_end(k)
        while len(self._d) > self.size:
            self._d.popitem(last=False)


class TurboQuant:
    def __init__(self):
        self._sem = asyncio.Semaphore(cfg.MAX_CONCURRENT_LLM)
        self._cache = _LRU(cfg.LLM_CACHE_SIZE)
        self._inflight: dict[str, asyncio.Future] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(model: str, prompt: str, temperature: float) -> str:
        h = hashlib.sha256(f"{model}|{temperature:.2f}|{prompt}".encode()).hexdigest()
        return h[:32]

    async def run(self, model: str, prompt: str, temperature: float,
                  call: Callable[[], Awaitable[str]]) -> str:
        """Cache + single-flight + concurrency-bounded execution of one LLM call."""
        # caching only makes sense for near-deterministic calls
        cacheable = temperature <= 0.2
        k = self.key(model, prompt, temperature)

        if cacheable:
            hit = self._cache.get(k)
            if hit is not None:
                self.hits += 1
                return hit
            # single-flight: if an identical call is already running, await it
            if k in self._inflight:
                return await self._inflight[k]

        self.misses += 1
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        if cacheable:
            self._inflight[k] = fut
        try:
            async with self._sem:
                result = await call()
            if cacheable:
                self._cache.put(k, result)
            if not fut.done():
                fut.set_result(result)
            return result
        except Exception as e:  # noqa: BLE001
            if not fut.done():
                fut.set_exception(e)
            raise
        finally:
            self._inflight.pop(k, None)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "cache_hits": self.hits,
            "cache_misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "max_concurrent": cfg.MAX_CONCURRENT_LLM,
        }


turbo = TurboQuant()
