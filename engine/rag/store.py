"""
Vector store — Qdrant (embedded now, server later), with a pure-python fallback
so the engine boots even before qdrant-client is installed.

The vector collection is shared infrastructure, but each point carries explicit
lane and sensitivity metadata. The retriever enforces authorization before any
stored text is returned to a caller.
"""
from __future__ import annotations
import asyncio
import uuid
import math
from typing import List, Optional

from ..config import cfg
from .embeddings import embedder


class _MemoryBackend:
    """Cosine-sim brute force. Fine for dev / small vaults; swap to Qdrant for scale."""
    def __init__(self):
        self._pts: list[tuple[str, list[float], dict]] = []

    def upsert(self, ids, vecs, payloads):
        for i, v, p in zip(ids, vecs, payloads):
            self._pts = [x for x in self._pts if x[0] != i]
            self._pts.append((i, v, p))

    def search(self, vec, limit, flt=None):
        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a)) or 1.0
            nb = math.sqrt(sum(y * y for y in b)) or 1.0
            return dot / (na * nb)
        cand = self._pts
        if flt:
            cand = [x for x in cand if all(x[2].get(k) == v for k, v in flt.items())]
        scored = sorted(((cos(vec, v), p) for _, v, p in cand), key=lambda t: -t[0])
        return [(s, p) for s, p in scored[:limit]]

    def count(self):
        return len(self._pts)

    def legacy_ids(self):
        valid_lanes = {"coding", "prompt", "marketing", "bizdev", "exec",
                       "general", "security", "shared", "global"}
        valid_sensitivity = {"public", "internal", "confidential", "restricted"}
        return [point_id for point_id, _, payload in self._pts
                if payload.get("lane") not in valid_lanes
                or payload.get("sensitivity") not in valid_sensitivity]

    def delete(self, ids):
        id_set = set(ids)
        before = len(self._pts)
        self._pts = [point for point in self._pts if point[0] not in id_set]
        return before - len(self._pts)

    def delete_tenant(self, tenant_id: str):
        return self.delete([point_id for point_id, _, payload in self._pts
                            if payload.get("tenant_id", "default") == tenant_id])


class VectorStore:
    def __init__(self):
        self.name = cfg.QDRANT_COLLECTION
        self._client = None
        self._mem: Optional[_MemoryBackend] = None
        self._ready = False

    async def init(self):
        if self._ready:
            return
        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams
            if cfg.QDRANT_URL:
                self._client = AsyncQdrantClient(url=cfg.QDRANT_URL)
            else:
                self._client = AsyncQdrantClient(path=cfg.QDRANT_PATH)
            existing = [c.name for c in (await self._client.get_collections()).collections]
            if self.name not in existing:
                await self._client.create_collection(
                    self.name,
                    vectors_config=VectorParams(size=embedder.dim, distance=Distance.COSINE),
                )
        except Exception as e:  # noqa: BLE001
            print(f"[store] Qdrant unavailable ({e}); using in-memory backend")
            self._client = None
            self._mem = _MemoryBackend()
        self._ready = True

    async def upsert(self, texts: List[str], payloads: List[dict],
                     ids: Optional[List[str]] = None):
        if len(texts) != len(payloads):
            raise ValueError("every vector text must have exactly one payload")
        if ids is not None and len(ids) != len(texts):
            raise ValueError("vector ids must match the number of texts")
        allowed_lanes = {"coding", "prompt", "marketing", "bizdev", "exec",
                         "general", "security", "shared", "global"}
        allowed_sensitivity = {"public", "internal", "confidential", "restricted"}
        for payload in payloads:
            if payload.get("lane") not in allowed_lanes:
                raise ValueError("vector payload requires a recognized lane")
            if payload.get("sensitivity") not in allowed_sensitivity:
                raise ValueError("vector payload requires a recognized sensitivity")
            payload.setdefault("tenant_id", "default")
            if payload.get("owner") and not payload.get("owner_sub"):
                payload["owner_sub"] = payload["owner"]
        await self.init()
        vecs: list[list[float] | None] = [None] * len(texts)
        positions_by_sensitivity: dict[str, list[int]] = {}
        for index, payload in enumerate(payloads):
            positions_by_sensitivity.setdefault(payload["sensitivity"], []).append(index)
        for sensitivity, positions in positions_by_sensitivity.items():
            embedded = await embedder.embed(
                [texts[index] for index in positions], sensitivity=sensitivity)
            for index, vector in zip(positions, embedded):
                vecs[index] = vector
        complete_vecs = [vector for vector in vecs if vector is not None]
        if len(complete_vecs) != len(texts):
            raise RuntimeError("embedding backend returned an incomplete vector batch")
        ids = ids or [str(uuid.uuid4()) for _ in texts]
        for p, t in zip(payloads, texts):
            p.setdefault("text", t)
        if self._client is not None:
            from qdrant_client.models import PointStruct
            pts = [PointStruct(id=i, vector=v, payload=p)
                   for i, v, p in zip(ids, complete_vecs, payloads)]
            await self._client.upsert(self.name, points=pts)
        else:
            self._mem.upsert(ids, complete_vecs, payloads)
        return ids

    async def search(self, query: str, limit: int = 6, flt: Optional[dict] = None,
                     sensitivity: str = "confidential", tenant_id: str = "default"):
        await self.init()
        qv = await embedder.embed_one(query, sensitivity=sensitivity)
        scoped_filter = dict(flt or {})
        scoped_filter["tenant_id"] = tenant_id
        if self._client is not None:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            qfilter = None
            if scoped_filter:
                qfilter = Filter(must=[FieldCondition(key=k, match=MatchValue(value=v))
                                       for k, v in scoped_filter.items()])
            res = await self._client.search(self.name, query_vector=qv, limit=limit,
                                            query_filter=qfilter)
            return [(r.score, r.payload) for r in res]
        return self._mem.search(qv, limit, scoped_filter)

    async def count(self) -> int:
        await self.init()
        if self._client is not None:
            return (await self._client.count(self.name)).count
        return self._mem.count()

    async def audit_legacy_points(self) -> list[str | int]:
        """Return IDs of points missing recognized lane or sensitivity metadata."""
        await self.init()
        if self._client is None:
            return self._mem.legacy_ids()
        valid_lanes = {"coding", "prompt", "marketing", "bizdev", "exec",
                       "general", "security", "shared", "global"}
        valid_sensitivity = {"public", "internal", "confidential", "restricted"}
        legacy_ids = []
        offset = None
        while True:
            points, offset = await self._client.scroll(
                collection_name=self.name, limit=256, offset=offset,
                with_payload=True, with_vectors=False)
            for point in points:
                payload = point.payload or {}
                if (payload.get("lane") not in valid_lanes
                        or payload.get("sensitivity") not in valid_sensitivity):
                    legacy_ids.append(point.id)
            if offset is None:
                return legacy_ids

    async def purge_legacy_points(self) -> int:
        """Delete only points flagged by audit_legacy_points and return the count."""
        await self.init()
        legacy_ids = await self.audit_legacy_points()
        if not legacy_ids:
            return 0
        if self._client is None:
            return self._mem.delete(legacy_ids)
        from qdrant_client.models import PointIdsList
        for start in range(0, len(legacy_ids), 256):
            await self._client.delete(
                collection_name=self.name,
                points_selector=PointIdsList(points=legacy_ids[start:start + 256]))
        return len(legacy_ids)

    async def delete_tenant(self, tenant_id: str) -> int:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        await self.init()
        if self._client is None:
            return self._mem.delete_tenant(tenant_id)
        from qdrant_client.models import Filter, FieldCondition, MatchValue, PointIdsList
        scoped = Filter(must=[FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))])
        point_ids = []
        offset = None
        while True:
            points, offset = await self._client.scroll(
                collection_name=self.name, scroll_filter=scoped, limit=256, offset=offset,
                with_payload=False, with_vectors=False)
            point_ids.extend(point.id for point in points)
            if offset is None:
                break
        for start in range(0, len(point_ids), 256):
            await self._client.delete(
                collection_name=self.name,
                points_selector=PointIdsList(points=point_ids[start:start + 256]))
        return len(point_ids)

    def backend_name(self) -> str:
        return "qdrant" if self._client is not None else "memory"


store = VectorStore()
