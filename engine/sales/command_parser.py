"""Conservative parser for authenticated user-originated sales commands."""
from __future__ import annotations

import re

from .services_catalog import SERVICES
from ..prompt_guard import contains_injection_pattern


def parse_sales_command(command: str, *, tainted: bool = False) -> dict:
    if tainted or contains_injection_pattern(command):
        return {"status": "rejected", "reason": "untrusted command source"}
    text = command.casefold()
    service = next((item for item in SERVICES
                    if item["id"].replace("_", " ") in text
                    or item["name"].casefold() in text), None)
    if any(word in text for word in ("call", "calling", "phone")):
        action = "voice_call"
    elif any(word in text for word in ("email", "outreach", "campaign")):
        action = "email_draft"
    elif any(word in text for word in ("lead", "prospect", "generate")):
        action = "lead_generation"
    else:
        return {"status": "clarification_required", "action": None,
                "missing_fields": ["action"]}
    geography_match = re.search(
        r"\b(?:in|within)\s+([A-Za-z][A-Za-z -]{1,60}?)"
        r"(?=[,.]|\s+(?:focusing|for|with|targeting)\b|$)", command, re.IGNORECASE)
    geography = geography_match.group(1).strip(" .,!") if geography_match else ""
    campaign_match = re.search(r"\bcampaign\s+([A-Za-z0-9_-]+)", command, re.IGNORECASE)
    missing = []
    if not service:
        missing.append("service_id")
    if action == "lead_generation" and not geography:
        missing.append("geography")
    if action in {"email_draft", "voice_call"} and not campaign_match:
        missing.append("campaign_id")
    if missing:
        return {"status": "clarification_required", "action": action,
                "missing_fields": missing}
    return {"status": "parsed", "action": action, "service_id": service["id"],
            "geography": geography, "campaign_id": campaign_match.group(1)
            if campaign_match else None, "explicit_voice_command": action == "voice_call"}
