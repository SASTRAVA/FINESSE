"""Fact-constrained email drafts; delivery is deliberately not implemented."""
from __future__ import annotations

from .services_catalog import get_service


def generate_email_draft(lead: dict, service_id: str) -> dict:
    service = get_service(service_id)
    if service is None:
        raise ValueError("unknown SASTRAVA sales service")
    if lead.get("service_id") != service_id:
        raise ValueError("lead is not matched to the requested service")
    body = service["template"].format(company=lead["company"])
    if any(claim.casefold() in body.casefold() for claim in service["disallowed_claims"]):
        raise ValueError("draft contains a disallowed claim")
    return {"subject": f"Discussing {service['name']} requirements",
            "body": body, "service_fit_rationale": "Service category matched by request.",
            "fact_references": ["approved_service_catalog"],
            "validation_result": {"valid": True, "unsupported_claims": []},
            "status": "draft", "delivery_enabled": False}
