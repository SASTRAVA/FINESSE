"""
Embeddings — the quantized workhorse.

Default backend = fastembed, which serves INT8-quantized ONNX BGE models on CPU.
That is the real "turboquant" for retrieval: ~sub-10ms/chunk, no GPU, no API,
no rate limit — so 30 users indexing/searching at once stays cheap and local.

`nim` backend calls NVIDIA hosted embeddings instead (needs NVIDIA_API_KEY).
`hash` backend is a deterministic fallback so the system still runs with zero deps.
"""
from __future__ import annotations
import asyncio
import hashlib
from typing import List

from ..config import cfg
from ..llm.provider import is_sensitive_for_egress, scrub_outbound

_DIM_FALLBACK = 384


class Embedder:
    def __init__(self):
        self.backend = cfg.EMBEDDINGS_BACKEND
        self._model = None
        self._dim = _DIM_FALLBACK
        self._init()

    def _init(self):
        if self.backend == "local":
            try:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name=cfg.EMBEDDINGS_MODEL_LOCAL)
                # bge-small = 384 dims
                self._dim = 384
                return
            except Exception as e:  # noqa: BLE001
                print(f"[embeddings] fastembed unavailable ({e}); using hash fallback")
                self.backend = "hash"
        if self.backend == "nim":
            self._dim = 1024  # nv-embedqa-e5-v5
            return
        self.backend = self.backend if self.backend in ("nim",) else "hash"

    @property
    def dim(self) -> int:
        return self._dim

    # ---- sync core (runs in threadpool from async callers) ----
    def _embed_local(self, texts: List[str]) -> List[List[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]

    def _embed_hash(self, texts: List[str]) -> List[List[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self._dim
            for tok in t.lower().split():
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                vec[h % self._dim] += 1.0
            n = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / n for x in vec])
        return out

    async def _embed_nim(self, texts: List[str], *, client=None) -> List[List[float]]:
        if client is None:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(base_url=cfg.NIM_BASE_URL, api_key=cfg.NVIDIA_API_KEY)
        resp = await client.embeddings.create(
            model=cfg.EMBEDDINGS_MODEL_NIM,
            input=[scrub_outbound(text, redact_pii=cfg.REDACT_PII_ON_EXTERNAL_LLM)
                   for text in texts],
            extra_body={"input_type": "passage"})
        return [d.embedding for d in resp.data]

    async def embed(self, texts: List[str], *, sensitivity: str = "internal") -> List[List[float]]:
        if not texts:
            return []
        sensitive = is_sensitive_for_egress(sensitivity)
        if (self.backend == "nim" and sensitive
                and not cfg.ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS):
            return await asyncio.to_thread(self._embed_hash, texts)
        if self.backend == "local":
            return await asyncio.to_thread(self._embed_local, texts)
        if self.backend == "nim":
            return await self._embed_nim(texts)
        return await asyncio.to_thread(self._embed_hash, texts)

    async def embed_one(self, text: str, *, sensitivity: str = "confidential") -> List[float]:
        return (await self.embed([text], sensitivity=sensitivity))[0]


embedder = Embedder()
