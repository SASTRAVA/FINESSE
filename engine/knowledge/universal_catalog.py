"""Finite, source-aware catalogs. Repository seeds remain unverified until gated."""
from __future__ import annotations

import re
FOUNDATION_MODULES = (
    "Identity", "Organization", "Permissions", "Data", "Knowledge", "Agents", "Tools",
    "Automation", "App Builder", "Security", "Governance", "Analytics", "Billing",
    "Marketplace", "Infrastructure",
)

PROFESSION_WORKSPACES = (
    "Developer", "Designer", "Marketing", "Content Creator", "Film Producer", "Accountant",
    "Lawyer", "Doctor / Clinic", "Teacher", "Real Estate", "Engineer", "Architect",
    "Researcher", "Recruiter", "Sales", "Consultant", "Restaurant", "Manufacturer",
)

WORKFLOW_PRIMITIVES = (
    "event_trigger", "schedule_trigger", "webhook_trigger", "manual_approval",
    "schema_validate", "schema_transform", "deduplicate_records", "route_by_policy",
    "quarantined_extract", "summarize_document", "classify_intent", "retrieve_knowledge",
    "index_knowledge", "capture_lead", "enrich_contact", "verify_contact",
    "score_lead", "match_service", "scope_proposal", "draft_email", "approve_campaign",
    "send_email_sandbox", "process_unsubscribe", "suppress_contact", "schedule_voice_sandbox",
    "record_human_handoff", "sync_crm", "schedule_calendar", "sync_invoice",
    "notify_owner", "create_audit_record", "check_security_scope", "verify_domain_ownership",
    "scan_surface_sandbox", "correlate_security_findings", "redact_evidence",
    "erase_tenant_data", "apply_retention_policy", "resolve_conflict", "retry_idempotently",
    "route_dead_letter", "export_tenant_data",
)

_REPOSITORY_ROWS = (
    ("langchain-ai/langgraph", "AI Agents"), ("crewAIInc/crewAI", "AI Agents"),
    ("microsoft/autogen", "AI Agents"), ("mem0ai/mem0", "AI Agents"),
    ("pydantic/pydantic-ai", "AI Agents"), ("browser-use/browser-use", "AI Agents"),
    ("pipecat-ai/pipecat", "AI Agents"), ("livekit/agents", "AI Agents"),
    ("openai/openai-agents-python", "AI Agents"), ("n8n-io/n8n", "Automation"),
    ("activepieces/activepieces", "Automation"), ("PrefectHQ/prefect", "Automation"),
    ("triggerdotdev/trigger.dev", "Automation"), ("windmill-labs/windmill", "Automation"),
    ("Skyvern-AI/skyvern", "Automation"), ("Wikkiee/LeadGenPy", "Automation"),
    ("microsoft/playwright", "Automation"),
    ("google/tsunami-security-scanner", "Security & Audit"),
    ("zaproxy/zaproxy", "Security & Audit"),
    ("projectdiscovery/nuclei", "Security & Audit"), ("anchore/grype", "Security & Audit"),
    ("trufflesecurity/trufflehog", "Security & Audit"),
    ("GitGuardian/ggshield", "Security & Audit"), ("Bearer/bearer", "Security & Audit"),
    ("OWASP/Nettacker", "Security & Audit"),
    ("DependencyTrack/dependency-track", "Security & Audit"),
    ("falcosecurity/falco", "Security & Audit"),
    ("prowler-cloud/prowler", "Security & Audit"), ("wazuh/wazuh", "Security & Audit"),
)

REPOSITORY_SEEDS = tuple({
    "full_name": full_name,
    "url": f"https://github.com/{full_name}",
    "category": category,
    "status": "DISCOVERED",
    "certification_stage": "SOURCE_INVENTORY_ONLY",
} for full_name, category in _REPOSITORY_ROWS)

assert len(FOUNDATION_MODULES) == 15
assert len(PROFESSION_WORKSPACES) == 18
assert len(WORKFLOW_PRIMITIVES) == 42
assert len(REPOSITORY_SEEDS) == 29

LICENSE_ALLOWLIST = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}


def certify_candidate(evidence: dict) -> dict:
    """Evaluate supplied evidence. Missing evidence always leaves the candidate unapproved."""
    gates = (
        ("PROVENANCE_CHECKED", bool(evidence.get("provenance_url")
                                    and evidence.get("repository_exists"))),
        ("LICENSE_CLEARED", evidence.get("license") in LICENSE_ALLOWLIST),
        ("MAINTENANCE_VERIFIED", bool(evidence.get("maintenance_verified"))),
        ("SUPPLY_CHAIN_CLEAN", bool(evidence.get("sbom_clean"))),
        ("STATIC_ANALYZED", bool(evidence.get("static_scan_clean"))),
        ("SANDBOX_TESTED", bool(evidence.get("sandbox_tested"))),
        ("INTEGRATION_VERIFIED", bool(evidence.get("mcp_contract_verified"))),
        ("PRODUCTION_APPROVED", bool(
            evidence.get("human_security_signoff")
            and re.fullmatch(r"[0-9a-fA-F]{64}", str(evidence.get("pinned_sha256", ""))))),
    )
    stage = "DISCOVERED"
    passed = []
    for gate, success in gates:
        if not success:
            break
        passed.append(gate)
        stage = gate
    return {"status": stage, "passed_gates": passed, "auto_approved": False}
