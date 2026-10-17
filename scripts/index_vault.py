"""
Index the Obsidian vault into the shared brain.

Walks vault/*.md, tags each chunk with a lane inferred from its top-level folder
(so retrieval respects role lanes), embeds (quantized) and upserts into Qdrant.
Run once after setup, and again whenever you add a lot of notes by hand:

    python run.py --index
"""
from __future__ import annotations
import asyncio
from pathlib import Path

from engine.config import cfg
from engine.rag.store import store
from engine.rag.ingest import chunk_text

# map top-level vault folders -> agent lanes
_LANE = {
    "04_AI_Agents": "shared", "16_MCP": "coding", "17_RAG": "coding", "18_Vector_DB": "coding",
    "12_Prompts": "prompt", "13_AI_Memory": "shared", "20_AI_Orchestration_Core": "shared",
    "10_Clients": "bizdev", "03_Roles": "shared", "11_Knowledge_Base": "shared",
}
_SKIP = {".obsidian", ".streamlit", "_Archived_Backup", "19_Archive", "lib"}


def _lane_for(rel: Path) -> str:
    top = rel.parts[0] if rel.parts else ""
    if "marketing" in str(rel).lower() or "seo" in str(rel).lower():
        return "marketing"
    return _LANE.get(top, "shared")


async def main():
    await store.init()
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
        lane = _lane_for(rel)
        for i, ch in enumerate(chunk_text(text)):
            batch_texts.append(ch)
            batch_meta.append({"title": p.stem, "role": lane, "source": "vault",
                               "path": str(rel), "chunk": i})
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
