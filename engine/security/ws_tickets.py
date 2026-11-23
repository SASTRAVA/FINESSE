"""Short-lived, opaque, single-use credentials for browser WebSocket upgrades."""
from __future__ import annotations

import hashlib
import secrets
import time

from ..db.storage import PlatformStorage, storage

TICKET_TTL_SECONDS = 60


def _ticket_id(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def issue_ticket(principal: dict, repository: PlatformStorage = storage) -> str:
    """Issue a one-use ticket bound to the authenticated principal and tenant."""
    tenant_id = str(principal.get("tenant_id", "default"))
    if not tenant_id:
        raise ValueError("tenant scope is required")
    ticket = secrets.token_urlsafe(32)
    record = {
        "status": "ISSUED",
        "sub": str(principal.get("sub", "")),
        "role": str(principal.get("role", "")),
        "tier": int(principal.get("tier", 1)),
        "tenant_id": tenant_id,
        "issued_at": time.time(),
        "expires_at": time.time() + TICKET_TTL_SECONDS,
    }
    if not record["sub"]:
        raise ValueError("principal subject is required")
    repository.put("ws_tickets", tenant_id, _ticket_id(ticket), record)
    return ticket


def consume_ticket(ticket: str, tenant_id: str = "default",
                   repository: PlatformStorage = storage) -> dict | None:
    """Atomically consume a ticket; raw ticket values are never persisted."""
    if not ticket or len(ticket) > 128 or not tenant_id:
        return None
    return repository.take_once("ws_tickets", tenant_id, _ticket_id(ticket))
