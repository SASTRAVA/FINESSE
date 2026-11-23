"""Immutable, expiring-token read-only portal snapshots."""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid

from ..audit.pg_audit import audit_log
from ..db.storage import storage


class PortalService:
    def __init__(self, repository=storage):
        self.repository = repository

    def publish(self, tenant_id: str, slug: str, deliverable: dict, *,
                sensitivity: str, publisher: str, approved_internal: bool = False,
                publisher_tier: int = 0, l4_override: bool = False) -> str:
        if sensitivity == "restricted" or sensitivity not in {"public", "internal", "confidential"}:
            raise PermissionError("restricted or invalid content cannot be published")
        if sensitivity == "internal" and (not approved_internal or publisher_tier < 3):
            raise PermissionError("internal portal content requires explicit clearance")
        if sensitivity == "confidential" and (not l4_override or publisher_tier < 4):
            raise PermissionError("confidential portal content requires an explicit L4 override")
        portal = self.repository.get("client_portals", tenant_id, slug) or {
            "tenant_id": tenant_id, "slug": slug, "status": "ACTIVE", "created_at": time.time()}
        if portal.get("status") != "ACTIVE":
            raise PermissionError("portal is revoked")
        self.repository.put("client_portals", tenant_id, slug, portal)
        snapshot_id = uuid.uuid4().hex
        self.repository.put("portal_shared_deliverables", tenant_id, snapshot_id, {
            "snapshot_id": snapshot_id, "portal_slug": slug,
            "deliverable": dict(deliverable), "sensitivity": sensitivity,
            "published_by": publisher, "published_at": time.time(), "immutable": True})
        audit_log.append(tenant_id, {"event": "portal.deliverable_published", "slug": slug,
                                     "snapshot_id": snapshot_id, "sensitivity": sensitivity,
                                     "publisher": publisher, "l4_override": l4_override})
        return snapshot_id

    def issue_access_token(self, tenant_id: str, slug: str, *, ttl_s: int = 3600) -> str:
        if ttl_s < 60 or ttl_s > 7 * 86400:
            raise ValueError("portal token TTL must be between one minute and seven days")
        portal = self.repository.get("client_portals", tenant_id, slug)
        if not portal or portal.get("status") != "ACTIVE":
            raise KeyError("active portal not found")
        token = secrets.token_urlsafe(32)
        token_id = hashlib.sha256(token.encode()).hexdigest()
        self.repository.put("client_portals", tenant_id, f"token:{token_id}", {
            "slug": slug, "expires_at": time.time() + ttl_s, "status": "ACTIVE"})
        return token

    def read(self, tenant_id: str, slug: str, token: str) -> list[dict]:
        token_id = hashlib.sha256(token.encode()).hexdigest()
        record = self.repository.get("client_portals", tenant_id, f"token:{token_id}")
        portal = self.repository.get("client_portals", tenant_id, slug)
        if (not record or record.get("slug") != slug or record.get("status") != "ACTIVE"
                or record.get("expires_at", 0) <= time.time()
                or not portal or portal.get("status") != "ACTIVE"):
            raise PermissionError("portal access is invalid, expired, or revoked")
        return [data for _, data in self.repository.list_items(
            "portal_shared_deliverables", tenant_id)
            if data.get("portal_slug") == slug]

    def revoke(self, tenant_id: str, slug: str, *, actor: str) -> None:
        portal = self.repository.get("client_portals", tenant_id, slug)
        if not portal:
            raise KeyError("portal not found")
        portal.update({"status": "REVOKED", "revoked_by": actor, "revoked_at": time.time()})
        self.repository.put("client_portals", tenant_id, slug, portal)
        audit_log.append(tenant_id, {"event": "portal.revoked", "slug": slug, "actor": actor})


portals = PortalService()
