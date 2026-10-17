"""Tenant-scoped sales funnel analytics."""
from __future__ import annotations

from ..db.storage import storage


def funnel(tenant_id: str) -> dict:
    leads = storage.list("leads", tenant_id, limit=1000)
    counts: dict[str, int] = {}
    for lead in leads:
        status = lead.get("status", "discovered")
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(leads), "by_status": counts,
            "eligible": sum(bool(lead.get("eligible_for_outreach")) for lead in leads)}
