from __future__ import annotations

import asyncio

from engine.rag.store import VectorStore


class CapturingQdrant:
    def __init__(self):
        self.kwargs = None

    async def search(self, *args, **kwargs):
        self.kwargs = kwargs
        return []

    async def query_points(self, **kwargs):
        self.kwargs = kwargs
        return type("Result", (), {"points": []})()


def test_qdrant_search_filter_contains_server_side_tenant_lane_acl_and_clearance():
    vectors = VectorStore()
    client = CapturingQdrant()
    vectors._client, vectors._ready = client, True

    async def embedded(_query, sensitivity):
        assert sensitivity == "confidential"
        return [0.1, 0.2]

    from unittest.mock import patch
    with patch("engine.rag.store.embedder.embed_one", new=embedded):
        asyncio.run(vectors.search(
            "invoice", tenant_id="tenant-a", sensitivity="confidential",
            flt={"tenant_id": "tenant-a", "lane": "general",
                 "sensitivity_allowed": ["public", "internal", "confidential"],
                 "is_active": True, "acl_principal_ids": ["alice@example.test"]}))

    filter_model = client.kwargs["query_filter"]
    assert filter_model.min_should.min_count == 1
    required = {(condition.key, str(condition.match.model_dump()))
                for condition in filter_model.must}
    assert any(key == "tenant_id" for key, _ in required)
    assert any(key == "lane" for key, _ in required)
    assert any(key == "is_active" for key, _ in required)
    assert {condition.key for condition in filter_model.min_should.conditions} == {
        "acl_restricted", "acl_principal_ids"}


def test_native_hybrid_prefetch_repeats_security_filter_on_each_branch(monkeypatch):
    from engine.config import cfg
    vectors = VectorStore()
    client = CapturingQdrant()
    vectors._client, vectors._ready, vectors._hybrid = client, True, True
    monkeypatch.setattr(cfg, "QDRANT_FUSION", "RRF")

    async def embedded(_query, sensitivity):
        return [0.1, 0.2]

    from unittest.mock import patch
    with patch("engine.rag.store.embedder.embed_one", new=embedded):
        asyncio.run(vectors.search(
            "exact SAST-INV-99482-ZX", tenant_id="tenant-a", limit=8,
            flt={"tenant_id": "tenant-a", "lane": "general",
                 "sensitivity_allowed": ["public", "internal"], "is_active": True,
                 "acl_principal_ids": ["alice@example.test"]}))
    assert len(client.kwargs["prefetch"]) == 2
    dense, bm25 = client.kwargs["prefetch"]
    assert dense.using == "dense" and bm25.using == "bm25"
    assert bm25.query.model.casefold() == "qdrant/bm25"
    assert dense.filter is client.kwargs["query_filter"]
    assert bm25.filter is client.kwargs["query_filter"]
