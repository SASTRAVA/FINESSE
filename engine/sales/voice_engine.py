"""Explicit-command-only voice call preview; never connects to telephony."""
from __future__ import annotations

from .compliance import calling_eligibility


def prepare_voice_call(*, lead: dict, service_id: str, tenant_id: str,
                       authorized_role: bool, explicit_command: bool,
                       confirmed: bool, consent_confirmed: bool,
                       approved_script: bool, handoff_requested: bool,
                       local_hour: int) -> dict:
    if not authorized_role or not explicit_command:
        raise PermissionError("voice calling requires an authorized explicit user command")
    if not confirmed:
        return {"status": "awaiting_confirmation", "call_placed": False}
    if not approved_script:
        raise PermissionError("an approved script is required")
    if not lead.get("eligible_for_outreach"):
        return {"status": "blocked", "reason": "lead is not eligible for outreach",
                "call_placed": False}
    eligible, reason = calling_eligibility(
        tenant_id=tenant_id, contact_id=lead["id"],
        consent_confirmed=consent_confirmed, local_hour=local_hour)
    if not eligible:
        return {"status": "blocked", "reason": reason, "call_placed": False}
    return {"status": "queued", "dry_run": True, "call_placed": False,
            "service_id": service_id,
            "human_handoff": "requested" if handoff_requested else "not_requested",
            "policy": reason}
