from __future__ import annotations

import asyncio

from engine.db.storage import PlatformStorage
from engine.rag.doc_lifecycle import DocumentLifecycle


class FakeVectorStore:
    def __init__(self):
        self.sequence = 0
        self.deactivated = []
        self.deleted = []

    async def upsert(self, texts, payloads):
        self.sequence += 1
        return [f"point-{self.sequence}-{index}" for index in range(len(texts))]

    async def deactivate_points(self, point_ids):
        self.deactivated.extend(point_ids)

    async def delete_points(self, point_ids):
        self.deleted.extend(point_ids)
        return len(point_ids)


def test_document_versions_supersede_old_points_and_tombstone(tmp_path):
    repository = PlatformStorage(str(tmp_path / "documents.db"))
    vectors = FakeVectorStore()
    lifecycle = DocumentLifecycle(repository, vectors)

    first = asyncio.run(lifecycle.index(
        "invoice v1", ["invoice v1"], tenant_id="tenant-a", source_type="UPLOAD",
        external_id="invoice-7", title="Invoice", lane="general",
        sensitivity="internal", actor="alice"))
    unchanged = asyncio.run(lifecycle.index(
        "invoice v1", ["invoice v1"], tenant_id="tenant-a", source_type="UPLOAD",
        external_id="invoice-7", title="Invoice", lane="general",
        sensitivity="internal", actor="alice"))
    second = asyncio.run(lifecycle.index(
        "invoice v2", ["invoice v2"], tenant_id="tenant-a", source_type="UPLOAD",
        external_id="invoice-7", title="Invoice", lane="general",
        sensitivity="internal", actor="alice"))

    assert first["doc_id"] == second["doc_id"]
    assert first["current_version"] == 1 and second["current_version"] == 2
    assert unchanged["unchanged"] is True
    assert first["point_ids"][0] in vectors.deactivated
    assert repository.get("knowledge_documents", "tenant-a", first["doc_id"])["current_version"] == 2

    deleted = asyncio.run(lifecycle.tombstone("tenant-a", first["doc_id"], "alice"))
    assert deleted["status"] == "TOMBSTONED" and deleted["deleted_points"] == 1
    assert second["point_ids"][0] in vectors.deleted
