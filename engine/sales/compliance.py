"""Fail-closed outbound eligibility and suppression helpers."""
from __future__ import annotations

import time

from ..db.storage import storage


def suppress_contact(tenant_id: str, contact_id: str, *, reason: str) -> None:
    storage.put("suppression_entries", tenant_id, contact_id, {
        "contact_id": contact_id, "reason": reason[:100], "created_at": time.time()})


def calling_eligibility(*, tenant_id: str, contact_id: str,
                        consent_confirmed: bool, local_hour: int) -> tuple[bool, str]:
    if storage.get("suppression_entries", tenant_id, contact_id):
        return False, "contact is suppressed"
    consent_record = storage.get("consent_records", tenant_id, contact_id)
    if (not consent_confirmed or not consent_record
            or not consent_record.get("consented")
            or consent_record.get("purpose") != "voice_call"):
        return False, "documented calling consent is required"
    if not 8 <= local_hour < 21:
        return False, "outside configured calling hours"
    return True, "eligible for sandbox preview only"
