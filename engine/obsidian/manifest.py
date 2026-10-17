"""
Vault manifest — the non-destructive Karpathy "wiring layer".

Instead of physically renumbering 900 notes, we add ONE explicit, machine-readable
map of how data is wired: which folders belong to which domain, and — crucially —
which engine module reads/writes each path. Agents, the DB, Claude, and any new
addition can read `vault_manifest.json` (or GET /api/manifest) to understand the
whole structure at a glance. A human-readable twin is written to
`00_Home/FINESSE_System_Map.md`.

Karpathy rule: the wiring is small, explicit, and in one place — no magic. Generated
from LIVE introspection (registry + mcp + a folder scan) so it can never drift.

  python run.py --manifest      # (re)generate both files
It is also refreshed on every `reweave` and on server startup.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

from ..config import cfg

# ---- the 5 Karpathy domains: the 22 numbered folders grouped by MEANING -------
# (folders are NOT moved — this is a logical overlay for easy data wiring)
DOMAINS: dict[str, dict] = {
    "Knowledge": {
        "desc": "What the org knows. Fed via the human gateway; retrieved by every agent.",
        "folders": ["06_Skills", "11_Knowledge_Base", "12_Prompts", "13_AI_Memory",
                    "17_RAG", "18_Vector_DB"],
    },
    "Organization": {
        "desc": "Who the org is — company, departments, roles, people.",
        "folders": ["01_Organization", "02_Departments", "03_Roles", "05_Human_Employees"],
    },
    "AI System": {
        "desc": "The orchestra itself — agents, tools, orchestration core, security.",
        "folders": ["04_AI_Agents", "16_MCP", "20_AI_Orchestration_Core", "22_Security"],
    },
    "Business": {
        "desc": "Going to market — SOPs, workflows, projects, clients, CRM.",
        "folders": ["07_SOP", "08_Workflows", "09_Projects", "10_Clients", "21_CRM"],
    },
    "Interface": {
        "desc": "How you see it — home, dashboards, live graph.",
        "folders": ["00_Home", "14_Dashboards", "15_Graphify"],
    },
    "Archive": {
        "desc": "Cold storage — not indexed into the live brain.",
        "folders": ["19_Archive"],
    },
}

# ---- the SINGLE source of truth for where the engine reads/writes the vault ----
# (documents the paths currently hardcoded across modules, so wiring is explicit)
ENGINE_PATHS: dict[str, dict] = {
    "injected_knowledge": {"path": "11_Knowledge_Base/_Injected", "module": "rag/ingest.py",
                           "io": "write", "by": "human-touch gateway"},
    "harvested_skills": {"path": "06_Skills/_Harvested", "module": "skills_harvester.py",
                         "io": "write", "by": "skill harvester + Hermes + security baseline"},
    "shared_memory": {"path": "13_AI_Memory/Shared_Consciousness.md", "module": "orchestra/memory.py",
                      "io": "read/write", "by": "every learning agent"},
    "deliverables": {"path": "09_Projects/_Deliverables", "module": "obsidian/mapper.py",
                     "io": "write", "by": "orchestrator (every directive)"},
    "engine_agents": {"path": "04_AI_Agents/_Engine", "module": "obsidian/weave.py",
                      "io": "write", "by": "reweave / startup sync"},
    "mcp_tools": {"path": "16_MCP/_Tools", "module": "obsidian/weave.py",
                  "io": "write", "by": "reweave"},
    "security_reports": {"path": "22_Security/_Reports", "module": "security_watch.py",
                         "io": "write", "by": "security audit agent"},
    "system_map": {"path": "00_Home/SASTRAVA OS MAP.md", "module": "obsidian/weave.py",
                   "io": "write", "by": "reweave"},
    "graph_map": {"path": "finesse_map.json", "module": "obsidian/mapper.py",
                  "io": "write", "by": "orchestrator (live directive->agent->deliverable)"},
    "manifest": {"path": "vault_manifest.json", "module": "obsidian/manifest.py",
                 "io": "write", "by": "this module (--manifest / reweave / startup)"},
}


def _folder_note_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for grp in DOMAINS.values():
        for f in grp["folders"]:
            d = cfg.VAULT / f
            counts[f] = sum(1 for _ in d.rglob("*.md")) if d.is_dir() else 0
    return counts


def build_manifest() -> dict:
    """Introspect the live system + vault and return the manifest dict."""
    from ..agents.registry import registry
    from ..mcp import mcp
    from ..auth.rbac import ROLES

    counts = _folder_note_counts()
    domains = {}
    for name, grp in DOMAINS.items():
        domains[name] = {
            "desc": grp["desc"],
            "folders": [{"name": f, "notes": counts.get(f, 0),
                         "exists": (cfg.VAULT / f).is_dir()} for f in grp["folders"]],
            "total_notes": sum(counts.get(f, 0) for f in grp["folders"]),
        }

    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "vault": str(cfg.VAULT),
        "principle": ("Non-destructive Karpathy wiring: folders stay put; this manifest is the "
                      "explicit, machine-readable map of how data flows. Read it to know where "
                      "anything lives and who reads/writes it."),
        "domains": domains,
        "engine_paths": ENGINE_PATHS,
        "lanes": sorted({r.lane for r in ROLES.values()}),
        "agents": [{"key": s.key, "title": s.title, "lane": s.lane, "model_role": s.model_role,
                    "uses_tools": s.uses_tools} for s in registry.all()],
        "tools": [{"name": t.name, "write": t.write, "lanes": list(t.lanes)} for t in mcp.all()],
        "endpoints_of_note": ["/api/manifest", "/api/graph", "/api/directive", "/api/voice",
                              "/api/security/audit", "/api/security/report", "/ws"],
    }


def _system_map_md(m: dict) -> str:
    lines = [
        "---", "title: FINESSE System Map", "tags: [map, home, wiring, karpathy]", "---", "",
        "# 🗺️ FINESSE System Map", "",
        "> The non-destructive **wiring layer**: the 22 vault folders grouped into 5+1 domains, "
        "and exactly which engine module reads/writes each path. Machine-readable twin: "
        "`vault_manifest.json` · live: `GET /api/manifest`.", "",
        f"_Generated {m['generated']}._", "",
        "## Domains",
    ]
    for name, d in m["domains"].items():
        lines.append(f"\n### {name} — {d['total_notes']} notes")
        lines.append(f"_{d['desc']}_\n")
        for f in d["folders"]:
            tick = "" if f["exists"] else "  ⚠️ _missing_"
            lines.append(f"- [[{f['name']} MOC|{f['name']}]] · {f['notes']} notes{tick}")
    lines += ["", "## Data wiring (engine ↔ vault)", "",
              "| Key | Path | Module | I/O | By |", "|---|---|---|---|---|"]
    for k, p in m["engine_paths"].items():
        lines.append(f"| `{k}` | `{p['path']}` | `{p['module']}` | {p['io']} | {p['by']} |")
    lines += ["", "## Live orchestra",
              f"- **Lanes:** {', '.join(m['lanes'])}",
              f"- **Agents ({len(m['agents'])}):** " + ", ".join(a["title"] for a in m["agents"]),
              f"- **Tools ({len(m['tools'])}):** " + ", ".join(t["name"] for t in m["tools"]),
              "", "> [[SASTRAVA OS MAP]] · [[FINESSE Live Graph]] · [[Security Posture]]", ""]
    return "\n".join(lines)


def _jarvis_note_md(m: dict) -> str:
    agents = " · ".join(f"[[{a['title'].replace(' ', '_')}]]" for a in m["agents"][:14])
    return (
        "---\ntitle: JARVIS\ntags: [jarvis, admin, hub, voice]\n---\n\n"
        "# 🧠 JARVIS — voice admin of FINESSE\n\n"
        "> The single voice interface that auto-detects intent and drives the whole platform with "
        "the CEO's privileges: research the web, build via the swarm, grow new agents, run security "
        "audits, and self-upgrade skills from open source. Talk to him at `http://localhost:8600`.\n\n"
        "## Wired into the whole system\n"
        "- [[FINESSE_System_Map]] — the complete wiring map\n"
        "- [[SASTRAVA OS MAP]] — master index\n"
        "- [[AI Agents MOC]] — the orchestra he commands\n"
        "- [[MCP Tools MOC]] — the tools (his hands)\n"
        "- [[Shared Consciousness]] — the evolving memory\n"
        "- [[Security Posture]] — the constant security watch\n"
        "- [[FINESSE Live Graph]] — the live 3D universe\n\n"
        f"## Agents at his command\n{agents}\n\n"
        "> When anything changes, JARVIS walks the whole loop — this note is his anchor in the graph.\n")


_INNOVATION_NOTE = (
    "---\ntitle: Innovation Hub\ntags: [innovation, hub, ideas, diagrams]\n---\n\n"
    "# ◈ Innovation Hub\n\n"
    "> The R&D surface of the ecosystem — where JARVIS turns ideas into research briefs, plans, and "
    "live analytical **Mermaid diagrams**. Open it from the dashboard (2nd tab, beside the Universe) "
    "at `/innovation`, or by voice: *\"research…\"*, *\"draw a diagram of…\"*.\n\n"
    "## Contents\n"
    "- Research briefs → `11_Knowledge_Base/_Research`\n"
    "- Generated diagrams → `14_Dashboards/_Diagrams`\n\n"
    "> SASTRAVA's own hub — opens as the dashboard **INNOVATION HUB** tab (`/innovation`).\n\n"
    "> [[JARVIS]] · [[FINESSE_System_Map]] · [[Advanced_Capabilities]] · [[SASTRAVA OS MAP]]\n")

_ADVANCED_NOTE = (
    "---\ntitle: Advanced_Capabilities\ntags: [advanced, capabilities, roadmap]\n---\n\n"
    "# 🚀 Advanced AI Capabilities — status\n\n"
    "How FINESSE maps to the advanced-AI checklist:\n\n"
    "| Capability | Status | Where |\n|---|---|---|\n"
    "| **Multi-Agent Collaboration** | ✅ | MCP tool layer + swarm + shared Qdrant brain — agents "
    "delegate & share context (`mcp/`, `orchestra/swarm.py`) |\n"
    "| **Agentic Workflows** | ✅ | `llm.agentic_loop` — plan → act with tools → observe → reflect |\n"
    "| **Autonomous Planning & Decision-Making** | ✅ | orchestrator planner + Hermes gap-analysis + "
    "JARVIS intent router self-organise toward outcomes |\n"
    "| **Reinforcement Learning & Fine-Tuning** | 🟡 | LoRA/QLoRA pipeline (`training/`) + reflection "
    "self-critique. RLHF/reward-modelling is the next step |\n"
    "| **Self-Learning AI Agents** | ✅ | reflection pass + shared memory confidence lifecycle "
    "(`orchestra/memory.py`) + Hermes self-evolution |\n"
    "| **Fully Autonomous Agents** | 🟡 | long-running loops (Hermes, crawler, security_watch, skill "
    "harvester) + memory + reflection — bounded by deliberate human-in-the-loop |\n\n"
    "> Design principle: autonomy WITH a human gate — agents produce deliverables & proposals; "
    "writes/external actions stay human-approved.\n\n> [[JARVIS]] · [[Innovation Hub]] · [[FINESSE_System_Map]]\n")


def write_manifest() -> dict:
    """Generate the manifest + System Map + JARVIS / Innovation / Advanced nodes. Returns stats."""
    m = build_manifest()
    (cfg.VAULT / "vault_manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    home = cfg.VAULT / "00_Home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "FINESSE_System_Map.md").write_text(_system_map_md(m), encoding="utf-8")
    (home / "JARVIS.md").write_text(_jarvis_note_md(m), encoding="utf-8")
    (home / "Innovation Hub.md").write_text(_INNOVATION_NOTE, encoding="utf-8")
    (home / "Advanced_Capabilities.md").write_text(_ADVANCED_NOTE, encoding="utf-8")
    return {"domains": len(m["domains"]), "agents": len(m["agents"]),
            "tools": len(m["tools"]),
            "total_notes": sum(d["total_notes"] for d in m["domains"].values())}
