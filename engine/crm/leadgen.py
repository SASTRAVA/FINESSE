"""
Lead generation — geo-aware, product-market-fit scored.

Flow: web_search("{icp} in {location}") + brain context -> LLM extracts structured
leads (need, fit_score, contact) -> DRAFTS outreach -> writes each into the Obsidian
CRM. Outreach is never sent here; a human approves + sends (the human-touch gateway).
"""
from __future__ import annotations
import json
import re

from ..llm import llm
from ..mcp import mcp
from ..knowledge.sastrava import SERVICES, infer_service_lines
from ..orchestra.events import bus
from .leads import crm, Lead

_SYS = ("You are Sastrava's Lead Generation Agent. From the provided web results and brain "
        "context, extract REAL potential B2B leads for the given ICP and location. For each, "
        "infer the likely business NEED we can serve and score product-market FIT 0..1. "
        "Classify each need using only these service_line IDs: strategy_consulting, ai_automation, "
        "software_delivery, cybersecurity, digital_growth, digital_learning. "
        "Also write a short, warm, human outreach draft (3-4 sentences, no spam). "
        "Return ONLY JSON: {\"leads\":[{\"company\":..,\"name\":..,\"title\":..,\"location\":..,"
        "\"industry\":..,\"need\":..,\"fit_score\":0.0,\"contact\":..,"
        "\"service_lines\":[..],\"outreach_draft\":..}]}")


async def generate_leads(*, icp: str, location: str, count: int = 5, owner: str = "",
                         trace: str = "", sensitivity: str = "internal") -> list[dict]:
    await bus.emit("system", "leadgen", f"hunting {count} leads: '{icp}' in {location}", trace=trace)

    # 1. geo-scoped search (keyless web_search tool)
    q = f"{icp} companies in {location}"
    web = await mcp.dispatch("web_search", {"query": q, "max_results": max(count, 5)},
                             lane="bizdev", actor="leadgen")
    web_txt = web.to_message() if web.ok else "(no web results)"

    # 2. brain context for fit
    ctx = await mcp.dispatch("vault_search", {"query": f"{icp} {location} client need offer"},
                             lane="bizdev", actor="leadgen")

    # 3. extract structured leads
    user = (f"ICP: {icp}\nLocation: {location}\nCount: {count}\n\n"
            f"# Web results\n{web_txt}\n\n# Brain context\n{ctx.to_message()}\n\n"
            f"Return JSON only.")
    raw = await llm.chat(_SYS, user, role="fast", temperature=0.3, max_tokens=1600,
                         sensitivity=sensitivity)
    parsed = _parse(raw)

    leads_out = []
    if not parsed:  # offline / parse fail -> seed one placeholder so the pipeline is testable
        parsed = [{"company": f"Prospect in {location}", "location": location, "industry": icp,
                   "need": "(enable NIM key for real extraction)", "fit_score": 0.4,
                   "outreach_draft": "Hi — noticed your work; would love to share how Sastrava can help."}]
    for item in parsed[:count]:
        if not isinstance(item, dict):
            continue
        valid_service_lines = {service["id"] for service in SERVICES}
        requested_services = item.get("service_lines", [])
        if not isinstance(requested_services, list):
            requested_services = []
        service_lines = [
            line for line in requested_services
            if isinstance(line, str) and line in valid_service_lines
        ][:3]
        if not service_lines:
            service_lines = infer_service_lines(
                f"{item.get('need', '')} {item.get('industry', icp)}")
        l = crm.add(
            company=item.get("company", ""), name=item.get("name", ""),
            title=item.get("title", ""), location=item.get("location", location),
            industry=item.get("industry", icp), need=item.get("need", ""),
            fit_score=float(item.get("fit_score", 0.5) or 0.5),
            contact=item.get("contact", ""), source="leadgen",
            outreach_draft=item.get("outreach_draft", ""),
            outreach_status="draft" if item.get("outreach_draft") else "none",
            service_lines=service_lines,
            owner=owner, status="new")
        leads_out.append({"id": l.id, "company": l.label(), "location": l.location,
                          "fit_score": l.fit_score, "service_lines": l.service_lines})
        await bus.emit("learn", "leadgen", f"lead: {l.label()} ({l.location}) fit {l.fit_score:.2f}",
                       trace=trace)
    await bus.emit("done", "leadgen", f"{len(leads_out)} leads into CRM (outreach awaits human)",
                   trace=trace)
    return leads_out


def _parse(text: str):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0)).get("leads", [])
    except Exception:  # noqa: BLE001
        return None
