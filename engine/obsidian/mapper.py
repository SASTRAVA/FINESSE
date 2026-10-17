"""
Obsidian mapper — live MD mapping.

Deliverables are written as Markdown notes with [[wikilinks]] to the roles and
agents involved, so Obsidian's native graph view lights up in real time as the
orchestra works. We also maintain finesse_map.json (nodes + edges) for the
custom dashboard graph, and can optionally PUSH into a running Obsidian via the
Local REST API plugin.

Point Obsidian at the FINESSE/vault folder and you get the live mapping you asked
for, for free — every run adds nodes and links.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

from ..config import cfg

_OUT = cfg.VAULT / "09_Projects" / "_Deliverables"
_MAP = cfg.VAULT / "finesse_map.json"


def _slug(s: str) -> str:
    return re.sub(r"[^\w\- ]", "_", s).strip()[:70] or "untitled"


def write_deliverable(directive: str, content: str, role: str, trace: str,
                      agent_roles: list[str], tenant_id: str = "default") -> str:
    output_dir = (_OUT if tenant_id == "default" else
                  cfg.VAULT / "_Tenants" / _slug(tenant_id) / "09_Projects" / "_Deliverables")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    title = f"{stamp}_{_slug(directive)[:50]}"
    note = output_dir / f"{title}.md"

    links = " ".join(f"[[{r}]]" for r in dict.fromkeys(agent_roles))
    front = ("---\n"
             f"title: {directive[:80]}\n"
             f"requested_by_role: {role}\n"
             f"trace: {trace}\n"
             f"agents: [{', '.join(dict.fromkeys(agent_roles))}]\n"
             f"tags: [deliverable, orchestra]\n"
             "---\n\n")
    body = (f"# {directive}\n\n"
            f"> Produced by the Sastrava orchestra · requested by **{role}** · trace `{trace}`\n\n"
            f"**Contributing agents:** {links or '(none)'}\n\n"
            f"---\n\n{content}\n")
    note.write_text(front + body, encoding="utf-8")

    rel = str(note.relative_to(cfg.VAULT))
    update_graph(directive=directive[:60], role=role, agent_roles=agent_roles, note=rel, trace=trace)
    push_to_obsidian_rest(rel, front + body)
    return rel


def update_graph(*, directive: str, role: str, agent_roles: list[str], note: str, trace: str):
    """Append nodes/edges to finesse_map.json (consumed by the dashboard graph)."""
    try:
        data = {"nodes": [], "edges": []}
        if _MAP.exists():
            data = json.loads(_MAP.read_text(encoding="utf-8"))
        seen = {n["id"] for n in data["nodes"]}

        def add_node(nid, kind):
            if nid not in seen:
                data["nodes"].append({"id": nid, "kind": kind})
                seen.add(nid)

        d_node = f"directive:{trace}"
        add_node(d_node, "directive")
        add_node(f"role:{role}", "role")
        data["edges"].append({"src": f"role:{role}", "dst": d_node, "rel": "requested"})
        for ar in dict.fromkeys(agent_roles):
            add_node(f"agent:{ar}", "agent")
            data["edges"].append({"src": d_node, "dst": f"agent:{ar}", "rel": "spawned"})
        add_node(f"note:{note}", "deliverable")
        data["edges"].append({"src": d_node, "dst": f"note:{note}", "rel": "produced"})

        data["nodes"] = data["nodes"][-2000:]
        data["edges"] = data["edges"][-4000:]
        _MAP.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[obsidian] graph update failed: {e}")


def push_to_obsidian_rest(rel_path: str, content: str):
    """Optional: push into a running Obsidian via Local REST API plugin."""
    if not cfg.OBSIDIAN_REST_URL or not cfg.OBSIDIAN_API_KEY:
        return
    try:
        import httpx
        url = cfg.OBSIDIAN_REST_URL.rstrip("/") + "/vault/" + rel_path.replace("\\", "/")
        httpx.put(url, content=content.encode("utf-8"),
                  headers={"Authorization": f"Bearer {cfg.OBSIDIAN_API_KEY}",
                           "Content-Type": "text/markdown"}, timeout=10)
    except Exception as e:  # noqa: BLE001
        print(f"[obsidian] REST push failed: {e}")
