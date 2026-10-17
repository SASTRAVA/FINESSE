"""Deterministic synthetic lead provider; no real contact discovery or enrichment."""
from __future__ import annotations

import hashlib
import time

from .scoring import score_lead
from .services_catalog import get_service

_LEAD_STATES = {"discovered", "enriched", "qualified", "eligible", "contacted",
                "engaged", "meeting_booked", "opportunity", "converted", "excluded",
                "invalid_contact", "suppressed", "unqualified", "closed_lost"}


def generate_sandbox_leads(*, service_id: str, geography: str,
                           industry: str = "startup", count: int = 5,
                           tenant_id: str = "default") -> list[dict]:
    service = get_service(service_id)
    if service is None:
        raise ValueError("unknown SASTRAVA sales service")
    if not geography.strip() or not 1 <= count <= 100:
        raise ValueError("geography and a count from 1 to 100 are required")
    leads = []
    for index in range(1, count + 1):
        company = f"Sandbox {service_id.replace('_', ' ').title()} Prospect {index:03d}"
        domain = f"sandbox-{tenant_id[:10]}-{index:03d}.example.test"
        lead_id = hashlib.sha256(f"{tenant_id}:{domain}".encode()).hexdigest()[:20]
        fit = score_lead(service_fit=0.8, industry_company_fit=0.6,
                         need_evidence=0.2, decision_maker_relevance=0.4,
                         contact_confidence=0.0)
        leads.append({
            "id": lead_id, "tenant_id": tenant_id, "company": company,
            "domain": domain, "name": f"Sandbox Contact {index:03d}",
            "email": f"contact{index:03d}@example.test", "phone": "",
            "service_id": service_id, "geography": geography.strip(),
            "industry": industry.strip(), "fit_score": fit["score"],
            "score_components": fit["components"], "status": "discovered",
            "source_metadata": {"provider": "deterministic_sandbox",
                                "record_type": "synthetic", "verified": False},
            "created_at": time.time(), "email_verification_status": "unknown",
            "phone_verification_status": "unknown", "fact_status": "inferred",
            "eligible_for_outreach": False,
        })
    if any(lead["status"] not in _LEAD_STATES for lead in leads):
        raise RuntimeError("sandbox lead lifecycle invariant failed")
    return leads
