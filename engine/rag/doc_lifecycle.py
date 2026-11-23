"""Tenant-scoped document version records and searchable-point lifecycle."""
from __future__ import annotations

import hashlib
import asyncio
import time

from ..db.storage import PlatformStorage, storage
from .store import VectorStore, store


class DocumentLifecycle:
    def __init__(self, repository: PlatformStorage = storage,
                 vector_store: VectorStore = store):
        self.repository, self.vector_store = repository, vector_store
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _lock(self, tenant_id: str, doc_id: str) -> asyncio.Lock:
        key = (tenant_id, doc_id)
        return self._locks.setdefault(key, asyncio.Lock())

    @staticmethod
    def document_id(tenant_id: str, source_type: str, external_id: str) -> str:
        value = f"{tenant_id}\0{source_type}\0{external_id}".encode("utf-8")
        return hashlib.sha256(value).hexdigest()[:32]

    async def index(self, text: str, chunks: list[str], *, tenant_id: str,
                    source_type: str, external_id: str, title: str, lane: str,
                    sensitivity: str, actor: str, source_label: str | None = None,
                    acl_principal_ids: list[str] | None = None) -> dict:
        if not chunks:
            raise ValueError("documents must contain at least one chunk")
        doc_id = self.document_id(tenant_id, source_type, external_id)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        async with self._lock(tenant_id, doc_id):
            existing = self.repository.get("knowledge_documents", tenant_id, doc_id)
            if (existing and existing.get("status") == "ACTIVE"
                    and existing.get("content_sha256") == digest):
                principals = list(acl_principal_ids or [])
                if existing.get("acl_principal_ids", []) != principals:
                    current_version = int(existing.get("current_version", 0))
                    version_record = self.repository.get(
                        "knowledge_document_versions", tenant_id,
                        f"{doc_id}:v{current_version}") or {}
                    point_ids = version_record.get("qdrant_point_ids", [])
                    await self.vector_store.update_point_acl(point_ids, principals)
                    existing["acl_principal_ids"] = principals
                    existing["updated_at"] = time.time()
                    self.repository.put("knowledge_documents", tenant_id, doc_id, existing)
                return {**existing, "unchanged": True}
            version = int(existing.get("current_version", 0) if existing else 0) + 1
            previous_version = int(existing.get("current_version", 0) if existing else 0)
            payloads = [{
                "doc_id": doc_id, "document_id": doc_id, "version": version,
                "title": title, "source": source_label or source_type.lower(),
                "source_type": source_type,
                "tenant_id": tenant_id, "lane": lane, "sensitivity": sensitivity,
                "is_active": True, "acl_principal_ids": list(acl_principal_ids or []),
                "acl_restricted": bool(acl_principal_ids), "owner": actor,
                "chunk": position, "n_chunks": len(chunks),
            } for position in range(len(chunks))]
            point_ids = await self.vector_store.upsert(chunks, payloads)
            version_record = {"doc_id": doc_id, "version": version,
                              "tenant_id": tenant_id, "content_sha256": digest,
                              "chunk_count": len(chunks), "qdrant_point_ids": point_ids,
                              "indexed_at": time.time(), "status": "ACTIVE"}
            self.repository.put("knowledge_document_versions", tenant_id,
                                f"{doc_id}:v{version}", version_record)
            record = {
                "doc_id": doc_id, "tenant_id": tenant_id, "source_type": source_type,
                "external_id": external_id, "title": title, "lane": lane,
                "sensitivity": sensitivity, "current_version": version,
                "content_sha256": digest, "acl_principal_ids": list(acl_principal_ids or []),
                "status": "ACTIVE", "updated_at": time.time(),
                "deleted_at": None, "indexed_by": actor,
            }
            self.repository.put("knowledge_documents", tenant_id, doc_id, record)
            if previous_version:
                previous = self.repository.get(
                    "knowledge_document_versions", tenant_id,
                    f"{doc_id}:v{previous_version}")
                if previous:
                    await self.vector_store.deactivate_points(previous.get(
                        "qdrant_point_ids", []))
                    previous["status"] = "SUPERSEDED"
                    previous["superseded_at"] = time.time()
                    self.repository.put("knowledge_document_versions", tenant_id,
                                        f"{doc_id}:v{previous_version}", previous)
            return {**record, "point_ids": point_ids, "unchanged": False}

    def get(self, tenant_id: str, doc_id: str) -> dict | None:
        return self.repository.get("knowledge_documents", tenant_id, doc_id)

    async def tombstone(self, tenant_id: str, doc_id: str, actor: str) -> dict:
        async with self._lock(tenant_id, doc_id):
            record = self.get(tenant_id, doc_id)
            if not record:
                raise KeyError("document not found")
            if record.get("status") == "TOMBSTONED":
                return {"doc_id": doc_id, "status": "TOMBSTONED", "deleted_points": 0}
            record.update({"status": "TOMBSTONED", "deleted_at": time.time(),
                           "deleted_by": actor, "updated_at": time.time()})
            # Durable tombstone is written first; the searchable active flag is
            # cleared before physical deletion so stale chunks cannot be returned.
            self.repository.put("knowledge_documents", tenant_id, doc_id, record)
            version = int(record.get("current_version", 0))
            version_record = self.repository.get(
                "knowledge_document_versions", tenant_id, f"{doc_id}:v{version}")
            point_ids = (version_record or {}).get("qdrant_point_ids", [])
            await self.vector_store.deactivate_points(point_ids)
            deleted = await self.vector_store.delete_points(point_ids)
            if version_record:
                version_record["status"] = "TOMBSTONED"
                self.repository.put("knowledge_document_versions", tenant_id,
                                    f"{doc_id}:v{version}", version_record)
            return {"doc_id": doc_id, "status": "TOMBSTONED", "deleted_points": deleted}


document_lifecycle = DocumentLifecycle()
