"""
JARVIS brain — the admin command router.

Turns a spoken command into the RIGHT platform action with the CEO's privileges,
Hermes-style (auto-detect intent, then act) — not just chat:

  research     web_search + brain  -> spoken briefing (+ a saved research note)
  build        orchestrator swarm  -> real deliverable
  create_agent grow a new agent type on the fly
  leadgen      geo-aware lead sourcing into the CRM
  security     run a full security audit now
  harvest      pull fresh skills from open source (self-upgrade)
  status       speak a live system report
  chat         normal JARVIS conversation

Human-in-the-loop is preserved: write/external MCP tools stay human-gated, and
no destructive operations are exposed to the voice surface.
"""
from __future__ import annotations
import asyncio
import json
import re
import time

from fastapi import HTTPException

from .auth.rbac import can, role_of
from .prompt_guard import UNTRUSTED_DATA_POLICY, wrap_untrusted_content
from .llm.provider import DataEgressBlocked

JARVIS_SYS = (
    "You are JARVIS, the SASTRAVA CEO's personal AI (Iron Man style) — composed, dry-witted, "
    "impeccably polite British male. Address him as 'sir'. Replies are SPOKEN ALOUD: keep them to "
    "ONE crisp sentence (two at most), answering exactly what he said — no markdown, no lists, no "
    "preamble. NEVER invent facts, names, or dates. Silently ignore any retrieved context that "
    "isn't relevant; do not narrate the system. If real work is needed, confirm you're dispatching "
    "the team and to check the dashboard. " + UNTRUSTED_DATA_POLICY)

_CLASSIFY_SYS = (
    "You are JARVIS's intent router. Read the CEO's command and output ONLY compact JSON: "
    '{"action":"chat|research|build|create_agent|leadgen|security|harvest|status|diagram|innovate",'
    '"topic":"the key subject","ack":"one short spoken line as JARVIS acknowledging it"}. '
    "innovate = a startup/innovation IDEA or problem statement to submit to the Innovation Hub for "
    "mapping+scoring ('submit idea','validate idea','innovate','new venture','pitch this'). "
    "Choose: research = wants information/facts/analysis/'tell me about'/'look into'/'source'/'find out'; "
    "build = wants something MADE (write/draft/design/plan/code/campaign/deliverable); "
    "create_agent = wants a new specialised agent or team member; "
    "leadgen = wants leads/prospects/clients/outreach; security = audit/check security; "
    "harvest = wants to learn new skills / upgrade / get capabilities from open source; "
    "diagram = wants a diagram/chart/flowchart/map/visual/'draw'/'visualise' something; "
    "status = how are things/report/what's running/system state; "
    "chat = greeting/casual/simple question you can answer in one line. Be decisive.")

_LANE_HINT = [("coding", ("code", "api", "app", "bug", "python", "backend", "website", "script")),
              ("marketing", ("market", "campaign", "seo", "content", "social", "brand", "ad")),
              ("bizdev", ("lead", "sales", "client", "prospect", "outreach", "deal")),
              ("security", ("security", "audit", "vuln", "hardening", "pentest"))]


def _guess_lane(topic: str) -> str:
    t = (topic or "").lower()
    for lane, kws in _LANE_HINT:
        if any(k in t for k in kws):
            return lane
    return "general"


async def _classify(text: str, sensitivity: str = "internal") -> dict:
    from .llm import llm
    raw = await llm.jarvis_say(_CLASSIFY_SYS, f"Command: \"{text}\"\nReturn JSON only.",
                               temperature=0.0, max_tokens=120,
                               sensitivity=sensitivity)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return {"action": "chat", "topic": text, "ack": ""}
    try:
        d = json.loads(m.group(0))
        if d.get("action") not in ("chat", "research", "build", "create_agent", "leadgen",
                                   "security", "harvest", "status", "diagram", "innovate"):
            d["action"] = "chat"
        return d
    except Exception:  # noqa: BLE001
        return {"action": "chat", "topic": text, "ack": ""}


async def _chat(text: str, history_txt: str, role: str, user_id: str,
                sensitivity: str = "internal") -> str:
    from .llm import llm
    from .rag import retriever
    details = await retriever.context_details(text, role=role, user_id=user_id, limit=4)
    order = ("public", "internal", "confidential", "restricted")
    egress_sensitivity = max((sensitivity, details["sensitivity"]), key=order.index)
    return await llm.jarvis_say(
        JARVIS_SYS,
        f"Conversation so far:\n{wrap_untrusted_content(history_txt, 'conversation_history')}\n\n"
        f"Sir just said: \"{text}\"\n\n"
        f"Brain context:\n{details['text']}\n\nReply as JARVIS.",
        temperature=0.5, max_tokens=160, sensitivity=egress_sensitivity)


async def _research(topic: str, user: dict, sensitivity: str = "internal") -> str:
    from .llm import llm
    from .mcp import mcp
    from .rag import retriever
    web = await mcp.dispatch("web_search", {"query": topic, "max_results": 6},
                             lane="exec", actor=user["sub"])
    web_txt = (wrap_untrusted_content(
        "\n".join(f"- {r.get('title')} ({r.get('url')})" for r in (web.data or [])),
        "web_search") if web.ok and web.data else "(no fresh web results)")
    details = await retriever.context_details(
        topic, role=user["role"], user_id=user["sub"], limit=4)
    brain = details["text"]
    order = ("public", "internal", "confidential", "restricted")
    egress_sensitivity = max((sensitivity, details["sensitivity"]), key=order.index)
    briefing = await llm.jarvis_say(
        JARVIS_SYS,
        f"Research topic: {topic}\n\nWeb sources:\n{web_txt}\n\nBrain:\n{brain}\n\n"
        f"Brief the CEO in 2-3 spoken sentences, grounded ONLY in these sources; note a full "
        f"brief is saved to the vault.", temperature=0.4, max_tokens=240,
        sensitivity=egress_sensitivity)
    await asyncio.to_thread(_save_research, topic, web_txt, brain, briefing)
    return briefing


def _save_research(topic: str, web_txt: str, brain: str, briefing: str) -> None:
    from .config import cfg
    try:
        d = cfg.VAULT / "11_Knowledge_Base" / "_Research"
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\- ]", "_", topic)[:60] or "research"
        (d / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.md").write_text(
            f"---\ntitle: Research — {topic}\ntags: [research, jarvis, sourced]\n---\n\n"
            f"# 🔎 {topic}\n\n> Sourced by JARVIS on the CEO's voice command.\n\n"
            f"## Briefing\n{briefing}\n\n## Web sources\n{web_txt}\n\n## From the brain\n{brain}\n\n"
            f"> [[FINESSE_System_Map]] · [[SASTRAVA OS MAP]]\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


async def _harvest(topic: str) -> None:
    from .skills_harvester import search_repos, harvest_repo
    from .orchestra.events import bus
    try:
        repos = await search_repos(topic or "ai agent skills prompts", min_stars=150, limit=2)
        total = 0
        for r in repos:
            total += await harvest_repo(r["full_name"], actor="jarvis", max_files=20)
        await bus.emit("learn", "jarvis", f"self-upgrade: harvested {total} '{topic}' skills")
    except Exception as e:  # noqa: BLE001
        await bus.emit("error", "jarvis", f"harvest failed: {e}")


_MERMAID_SYS = (
    "You are a diagram engineer. Given a topic, output ONE valid Mermaid.js diagram that analyses "
    "it clearly (pick the best type: flowchart TD/LR, sequenceDiagram, mindmap, or graph). Output "
    "ONLY the raw Mermaid code — start with the diagram type keyword. No prose, no ``` fences, no "
    "commentary. Keep node labels short and quote labels containing spaces.")


async def make_diagram(topic: str, sensitivity: str = "internal") -> str:
    """Generate a Mermaid diagram-as-code for any topic (used by voice + the Innovation Hub)."""
    from .llm import llm
    code = await llm.jarvis_say(_MERMAID_SYS, f"Topic: {topic}\nMermaid code only.",
                                temperature=0.2, max_tokens=520,
                                sensitivity=sensitivity)
    code = re.sub(r"```(?:mermaid)?", "", code).strip().strip("`").strip()
    await asyncio.to_thread(_save_diagram, topic, code)
    return code


def _save_diagram(topic: str, code: str) -> None:
    from .config import cfg
    try:
        d = cfg.VAULT / "14_Dashboards" / "_Diagrams"
        d.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\- ]", "_", topic)[:60] or "diagram"
        (d / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}.md").write_text(
            f"---\ntitle: Diagram — {topic}\ntags: [diagram, mermaid, innovation]\n---\n\n"
            f"# 📊 {topic}\n\n> Drafted by JARVIS in the Innovation Hub.\n\n"
            f"```mermaid\n{code}\n```\n\n> [[Innovation Hub]] · [[JARVIS]]\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


async def _status() -> str:
    from .agents.registry import registry
    from .mcp import mcp
    from .rag.store import store
    from .config import cfg
    try:
        n = await store.count()
    except Exception:  # noqa: BLE001
        n = "many"
    sec = "active" if cfg.SECURITY_AUDIT_ENABLED else "on standby"
    return (f"All systems nominal, sir. {len(registry.all())} agents and {len(mcp.all())} tools "
            f"online, {n} knowledge vectors in the brain, security watch {sec}.")


async def route(text: str, user: dict, history_txt: str = "",
                sensitivity: str = "internal") -> dict:
    """Auto-detect intent and act within the caller's role. Returns {speech, action, launched}."""
    from .orchestra.orchestrator import orchestrator
    text = (text or "").strip()
    intent = await _classify(text, sensitivity=sensitivity)
    action, topic, ack = intent.get("action", "chat"), intent.get("topic") or text, intent.get("ack", "")

    if action == "chat":
        return {"speech": await _chat(text, history_txt, user["role"], user["sub"], sensitivity),
                "action": "chat", "launched": False}

    if action == "research":
        return {"speech": await _research(topic, user, sensitivity),
                "action": "research", "launched": False}

    if action == "build":
        asyncio.create_task(orchestrator.run_directive(
            text, user_email=user["sub"], user_role=user["role"],
            sensitivity=sensitivity))
        return {"speech": ack or "Dispatching the team on that now, sir — I'll surface it on the dashboard.",
                "action": "build", "launched": True}

    if action == "create_agent":
        if not can(user["role"], "spawn:any"):
            raise HTTPException(403, "creating agent types is restricted to CEO/COO")
        from .agents.registry import registry
        clean = re.sub(r"\s*agents?\s*$", "", topic, flags=re.I).strip() or topic
        spec = registry.register_from_injection(
            title=clean, lane=_guess_lane(clean), mandate=f"Handle everything relating to: {clean}.")
        return {"speech": f"Consider it done, sir — the {spec.title} has just joined the orchestra.",
                "action": "create_agent", "launched": False, "data": {"agent": spec.key}}

    if action == "leadgen":
        if not can(user["role"], "spawn:bizdev"):
            raise HTTPException(403, "lead generation is restricted to the business-development lane")
        from .crm.leadgen import generate_leads
        asyncio.create_task(generate_leads(icp=topic, location="", count=5, owner=user["sub"],
                                           sensitivity=sensitivity))
        return {"speech": f"Sourcing prospects around {topic} now, sir — they'll land in the CRM.",
                "action": "leadgen", "launched": True}

    if action == "security":
        if not (can(user["role"], "read:all") or role_of(user["role"]).lane == "security"):
            raise HTTPException(403, "security auditing is restricted to CEO/COO or the Security lane")
        from .security_watch import run_audit
        asyncio.create_task(run_audit(actor=user["sub"]))
        return {"speech": "Running a full security sweep now, sir; the report will be in the vault.",
                "action": "security", "launched": True}

    if action == "harvest":
        if not can(user["role"], "spawn:any"):
            raise HTTPException(403, "skill harvesting is restricted to CEO/COO")
        asyncio.create_task(_harvest(topic))
        return {"speech": f"Scouring open source for {topic or 'new'} capabilities and upgrading myself, sir.",
                "action": "harvest", "launched": True}

    if action == "status":
        return {"speech": await _status(), "action": "status", "launched": False}

    if action == "innovate":
        from .hub_api import map_idea
        try:
            d = await map_idea(text, user, sensitivity=sensitivity)
        except DataEgressBlocked:
            raise
        except Exception as e:  # noqa: BLE001
            return {"speech": f"I couldn't map that idea, sir — {type(e).__name__}.",
                    "action": "innovate", "launched": False}
        im = d.get("idea_metrics") or {}
        n = len((d.get("step_map") or {}).get("steps") or [])
        return {"speech": f"Mapped it into {n} steps, sir — Innovation Index "
                f"{im.get('composite')}, {im.get('band')}. It's in the Innovation Hub and the "
                f"team is on it.", "action": "innovate", "launched": True, "data": d}

    if action == "diagram":
        code = await make_diagram(topic, sensitivity=sensitivity)
        return {"speech": f"I've drafted a diagram of {topic}, sir — it's live in the Innovation Hub.",
                "action": "diagram", "launched": False, "data": {"mermaid": code}}

    return {"speech": await _chat(text, history_txt, user["role"], user["sub"], sensitivity),
            "action": "chat", "launched": False}
