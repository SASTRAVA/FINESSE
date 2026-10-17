"""
Weave — one-sweep Obsidian reconstruction for workflow + graph performance.

What it does (idempotent, safe to re-run):
  1. sync_agents()      — write EVERY engine agent (coding/prompt/marketing + all) as a note
  2. map_layer()        — MOCs (Maps of Content) for skills, MCP connectors, tools, memory, CRM
  3. build_folder_mocs()— one _MOC per top-level folder linking its notes (kills folder orphans)
  4. connect_orphans()  — every note with no links gets woven into its folder MOC + hub
  5. master_index()     — 00_Home/SASTRAVA_OS_MAP.md links all MOCs, agents, tools, CRM
  6. tune_graph()       — .obsidian graph settings for faster, readable rendering

Latency note: an Obsidian graph slows down mostly from thousands of DISCONNECTED nodes.
Hub-and-spoke MOCs + zero orphans render far faster and are easier to navigate.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from ..config import cfg

V = cfg.VAULT
_LINK = re.compile(r"\[\[([^\]|#]+)")
_SKIP_DIRS = {".obsidian", ".streamlit", "lib", "_Archived_Backup"}


# ---------------------------------------------------------------- helpers
def _iter_md():
    for p in V.rglob("*.md"):
        if any(s in p.parts for s in _SKIP_DIRS):
            continue
        yield p


def _top(p: Path) -> str:
    rel = p.relative_to(V)
    return rel.parts[0] if len(rel.parts) > 1 else "00_Home"


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _front(title: str, tags: list[str], extra: dict | None = None) -> str:
    lines = ["---", f"title: {title}", f"tags: [{', '.join(tags)}]"]
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


# ---------------------------------------------------------------- 1. agents
def sync_agents() -> int:
    from ..agents.registry import registry
    from ..mcp import mcp
    out = V / "04_AI_Agents" / "_Engine"
    n = 0
    for s in registry.all():
        tools = [t.name for t in mcp.for_lane(s.lane)]
        note = out / f"{s.title.replace(' ', '_')}.md"
        body = (
            _front(s.title, ["agent", "engine", s.lane],
                   {"lane": s.lane, "model_role": s.model_role, "spawnable": s.spawnable})
            + f"\n# {s.title}\n\n"
            f"Live engine agent. **Lane:** [[{s.lane} MOC]] · **Model tier:** `{s.model_role}` · "
            f"learns: {s.learns}\n\n"
            f"## Mandate\n```\n{s.system_prompt}\n```\n\n"
            f"## Tools available (RBAC-scoped)\n"
            + ("".join(f"- [[{t}]]\n" for t in tools) or "- (none)\n")
            + f"\n## Wired into\n- [[SASTRAVA OS MAP]]\n- [[AI Agents MOC]]\n"
            f"- [[Shared Consciousness]] (contributes patterns)\n"
        )
        _write(note, body)
        n += 1
    return n


# ---------------------------------------------------------------- 2. layer maps
def map_layer() -> dict:
    from ..agents.registry import registry
    from ..mcp import mcp
    stats = {}

    # AI Agents MOC
    agent_links = "\n".join(f"- [[{s.title.replace(' ', '_')}]] — `{s.lane}`"
                            for s in registry.all())
    _write(V / "04_AI_Agents" / "AI Agents MOC.md",
           _front("AI Agents MOC", ["moc", "agents"]) +
           "\n# AI Agents MOC\n\nEvery live agent in the orchestra.\n\n" + agent_links +
           "\n\n> New agents auto-appear here after `reweave`. Back to [[SASTRAVA OS MAP]].\n")

    # Tools / Connectors MOC
    tool_links = "\n".join(f"- [[{t.name}]] — {'write (human-gated)' if t.write else 'read'} · "
                           f"lanes: {', '.join(t.lanes)}" for t in mcp.all())
    for t in mcp.all():
        _write(V / "16_MCP" / "_Tools" / f"{t.name}.md",
               _front(t.name, ["tool", "connector", "mcp"],
                      {"write": t.write, "lanes": ", ".join(t.lanes)}) +
               f"\n# {t.name}\n\n{t.description}\n\n"
               f"- Write/action: **{t.write}** {'(requires human approval)' if t.write else ''}\n"
               f"- Allowed lanes: {', '.join(t.lanes)}\n\n> [[MCP Tools MOC]] · [[SASTRAVA OS MAP]]\n")
    _write(V / "16_MCP" / "MCP Tools MOC.md",
           _front("MCP Tools MOC", ["moc", "mcp", "tools"]) +
           "\n# MCP Tools MOC\n\nThe agents' hands (RBAC-gated, audited, writes human-gated).\n\n" +
           tool_links + "\n\n> Back to [[SASTRAVA OS MAP]].\n")
    stats["tools"] = len(mcp.all())
    stats["agents"] = len(registry.all())
    return stats


# ---------------------------------------------------------------- 3. folder MOCs
def build_folder_mocs() -> dict:
    folders: dict[str, list[Path]] = {}
    for p in _iter_md():
        if p.name.endswith("_MOC.md") or p.name == "SASTRAVA OS MAP.md":
            continue
        folders.setdefault(_top(p), []).append(p)
    made = {}
    for folder, files in folders.items():
        fdir = V / folder
        if not fdir.is_dir():
            continue
        links = "\n".join(f"- [[{f.stem}]]" for f in sorted(files, key=lambda x: x.stem))
        _write(fdir / f"{folder}_MOC.md",
               _front(f"{folder} MOC", ["moc", folder]) +
               f"\n# {folder} — Map of Content\n\n{len(files)} notes.\n\n{links}\n\n"
               f"> Hub for this domain. Back to [[SASTRAVA OS MAP]].\n")
        made[folder] = len(files)
    return made


# ---------------------------------------------------------------- 4. orphans
def _index_links():
    inbound: dict[str, int] = {}
    outbound: dict[str, int] = {}
    files = list(_iter_md())
    stems = {p.stem for p in files}
    for p in files:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        links = [m.group(1).strip() for m in _LINK.finditer(txt)]
        outbound[p.stem] = len(links)
        for l in links:
            if l in stems:
                inbound[l] = inbound.get(l, 0) + 1
    return files, inbound, outbound


def connect_orphans() -> dict:
    files, inbound, outbound = _index_links()
    orphans_before = [p for p in files
                      if inbound.get(p.stem, 0) == 0 and outbound.get(p.stem, 0) == 0
                      and not p.name.endswith("_MOC.md")]
    fixed = 0
    for p in orphans_before:
        folder = _top(p)
        moc = f"{folder} MOC"
        txt = p.read_text(encoding="utf-8", errors="ignore")
        weave = (f"\n\n---\n> 🔗 *Woven by reweave:* part of [[{moc}]] · "
                 f"[[SASTRAVA OS MAP]] · [[00_Master_Brain_Hub]]\n")
        if "Woven by reweave" not in txt:
            p.write_text(txt + weave, encoding="utf-8")
            fixed += 1
    return {"orphans_before": len(orphans_before), "orphans_connected": fixed}


# ---------------------------------------------------------------- 5. master index
def master_index(stats: dict):
    folders = sorted({_top(p) for p in _iter_md() if (V / _top(p)).is_dir()})
    moc_links = "\n".join(f"- [[{f} MOC]]" for f in folders)
    body = (
        _front("SASTRAVA OS MAP", ["moc", "home", "map"]) +
        "\n# 🧠 SASTRAVA OS MAP\n\nThe single entry point. Everything connects back here.\n\n"
        "## Core layers\n"
        "- [[AI Agents MOC]] — the orchestra\n"
        "- [[MCP Tools MOC]] — connectors & tools\n"
        "- [[CRM Pipeline]] — leads & clients\n"
        "- [[Shared Consciousness]] — evolving memory\n"
        "- [[00_Master_Brain_Hub]] — original brain hub\n\n"
        f"## Domain maps ({len(folders)})\n{moc_links}\n\n"
        "## System stats (last reweave)\n"
        + "".join(f"- **{k}**: {v}\n" for k, v in stats.items())
        + "\n> Run `python run.py --reweave` after big changes to re-connect everything.\n"
    )
    _write(V / "00_Home" / "SASTRAVA OS MAP.md", body)


# ---------------------------------------------------------------- 6. graph perf
def tune_graph():
    cfgp = V / ".obsidian" / "graph.json"
    settings = {
        "collapse-filter": True, "search": "", "showTags": True, "showAttachments": False,
        "hideUnresolved": True, "showOrphans": False,
        "collapse-color-groups": False,
        "colorGroups": [
            {"query": "tag:#agent", "color": {"a": 1, "rgb": 12213759}},
            {"query": "tag:#moc", "color": {"a": 1, "rgb": 16755285}},
            {"query": "tag:#tool", "color": {"a": 1, "rgb": 5025434}},
            {"query": "tag:#lead", "color": {"a": 1, "rgb": 16733525}},
            {"query": "tag:#memory", "color": {"a": 1, "rgb": 16777045}},
        ],
        "collapse-display": True, "showArrow": True, "textFadeMultiplier": -0.7,
        "nodeSizeMultiplier": 1.1, "lineSizeMultiplier": 1,
        "collapse-forces": True, "centerStrength": 0.52, "repelStrength": 8,
        "linkStrength": 1, "linkDistance": 220, "scale": 0.7, "close": True,
    }
    try:
        _write(cfgp, json.dumps(settings, indent=2))
    except Exception as e:  # noqa: BLE001
        print(f"[weave] graph tune skipped: {e}")


# ---------------------------------------------------------------- orchestrate
def reweave() -> dict:
    stats = {}
    stats["engine_agents_written"] = sync_agents()
    stats.update(map_layer())
    stats["folder_mocs"] = len(build_folder_mocs())
    stats.update(connect_orphans())
    master_index(stats)
    tune_graph()
    # refresh the non-destructive Karpathy wiring layer (manifest + System Map)
    try:
        from .manifest import write_manifest
        stats["manifest"] = write_manifest()
    except Exception as e:  # noqa: BLE001
        print(f"[weave] manifest skipped: {e}")
    return stats
