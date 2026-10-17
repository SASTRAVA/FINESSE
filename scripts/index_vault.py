"""
Index the Obsidian vault into the shared brain.

Walks vault/*.md, tags each chunk with a lane inferred from its top-level folder
(so retrieval respects role lanes), embeds (quantized) and upserts into Qdrant.
Run once after setup, and again whenever you add a lot of notes by hand:

    python run.py --index
"""
from __future__ import annotations
import asyncio
import argparse
import re
from pathlib import Path

from engine.config import cfg
from engine.rag.store import store
from engine.rag.ingest import chunk_text

# map top-level vault folders -> agent lanes
_LANE = {
    "04_AI_Agents": "shared", "16_MCP": "coding", "17_RAG": "coding", "18_Vector_DB": "coding",
    "12_Prompts": "prompt", "13_AI_Memory": "exec", "20_AI_Orchestration_Core": "exec",
    "10_Clients": "bizdev", "03_Roles": "exec", "11_Knowledge_Base": "shared",
}
_SKIP = {".obsidian", ".streamlit", "_Archived_Backup", "19_Archive", "lib"}


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"\A---\s*\n(.*?)\n---(?:\s|\Z)", text, re.DOTALL)
    if not match:
        return {}
    return {key: value.strip().strip('"\'') for key, value in
            re.findall(r"(?m)^(role|lane|sensitivity|injected_by):\s*(.*?)\s*$",
                       match.group(1))}


def _lane_for(rel: Path, metadata: dict[str, str] | None = None) -> str:
    top = rel.parts[0] if rel.parts else ""
    if top in {"01_Executive", "02_Executive", "03_Roles", "13_AI_Memory",
               "20_AI_Orchestration_Core"}:
        return "exec"
    if "_Injected" in rel.parts:
        lane = (metadata or {}).get("lane") or (metadata or {}).get("role", "")
        if lane in {"coding", "prompt", "marketing", "bizdev", "exec", "general", "security"}:
            return lane
        return "exec"
    if "marketing" in str(rel).lower() or "seo" in str(rel).lower():
        return "marketing"
    return _LANE.get(top, "general")


def _sensitivity_for(lane: str, rel: Path, metadata: dict[str, str] | None = None) -> str:
    path = str(rel).lower()
    declared = (metadata or {}).get("sensitivity", "")
    if lane == "exec" or any(word in path for word in (
            "10_clients", "confidential", "restricted", "private", "finance", "hr", "legal")):
        order = ("public", "internal", "confidential", "restricted")
        return max(("confidential", declared if declared in order else "confidential"),
                   key=order.index)
    if declared in {"public", "internal", "confidential", "restricted"}:
        return declared
    if "_injected" in path:
        return "confidential"
    return "internal"


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description="Index the configured Markdown vault.")
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--purge-legacy", action="store_true",
                         help="delete vector points with missing/invalid lane or sensitivity")
    options.add_argument("--audit-only", action="store_true",
                         help="report the number of legacy points without changing data")
    return parser.parse_args(argv)


async def main(argv=None):
    args = _arguments(argv)
    await store.init()
    if args.audit_only:
        legacy = await store.audit_legacy_points()
        print(f"[index] audit complete: {len(legacy)} legacy vector points")
        return
    if args.purge_legacy:
        removed = await store.purge_legacy_points()
        print(f"[index] purged {removed} legacy vector points")
    files = [p for p in cfg.VAULT.rglob("*.md")
             if not any(s in p.parts for s in _SKIP)]
    print(f"[index] {len(files)} markdown files under {cfg.VAULT}")

    batch_texts, batch_meta, total = [], [], 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(text.strip()) < 40:
            continue
        rel = p.relative_to(cfg.VAULT)
        frontmatter = _frontmatter(text)
        lane = _lane_for(rel, frontmatter)
        private_injection = "_Injected" in rel.parts
        sensitivity = _sensitivity_for(lane, rel, frontmatter)
        owner = frontmatter.get("injected_by", "") if private_injection else ""
        for i, ch in enumerate(chunk_text(text)):
            batch_texts.append(ch)
            batch_meta.append({"title": p.stem, "role": lane, "lane": lane,
                               "sensitivity": sensitivity,
                               "source": "vault_injected" if private_injection else "vault",
                               "owner": owner, "path": str(rel), "chunk": i})
            if len(batch_texts) >= 64:
                await store.upsert(batch_texts, batch_meta)
                total += len(batch_texts)
                batch_texts, batch_meta = [], []
                print(f"[index] {total} chunks…", end="\r")
    if batch_texts:
        await store.upsert(batch_texts, batch_meta)
        total += len(batch_texts)
    print(f"\n[index] done. {total} chunks in the brain ({store.backend_name()}).")


if __name__ == "__main__":
    asyncio.run(main())
