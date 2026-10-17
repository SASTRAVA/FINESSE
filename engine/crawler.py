"""
Background growth loops (opt-in via .env). Two async heartbeats:

  crawl_loop()   — every CRAWLER_INTERVAL_MIN: run configured web searches, ingest
                   fresh snippets into the brain, and (optionally) generate leads.
                   The brain "keeps growing" while humans stay on outreach.
  reweave_loop() — every REWEAVE_INTERVAL_MIN: re-connect all nodes/agents/tools so
                   the graph never drifts into orphans.

Both are rate-limited, cancellable, and OFF by default. Enable deliberately:
  CRAWLER_ENABLED=1  CRAWLER_QUERIES="ai course leads Bangalore, edtech startups India"
  REWEAVE_INTERVAL_MIN=60
"""
from __future__ import annotations
import asyncio
import time

from .config import cfg
from .mcp import mcp
from .rag.ingest import ingest_text
from .orchestra.events import bus

_tasks: list[asyncio.Task] = []


async def crawl_loop():
    await bus.emit("system", "crawler", f"crawler online ({cfg.CRAWLER_INTERVAL_MIN}m interval)")
    while True:
        try:
            for q in cfg.CRAWLER_QUERIES:
                res = await mcp.dispatch("web_search", {"query": q, "max_results": 6},
                                         lane="general", actor="crawler")
                if res.ok and res.data:
                    text = "\n".join(f"{r.get('title','')} — {r.get('url','')}" for r in res.data)
                    await ingest_text(text, title=f"crawl: {q[:40]}", role="general",
                                      injected_by="crawler", source="crawl")
                    await bus.emit("memory", "crawler", f"ingested {len(res.data)} results for '{q}'")
                await asyncio.sleep(2)  # be polite
            if cfg.CRAWLER_LEADGEN and cfg.CRAWLER_LOCATION:
                from .crm.leadgen import generate_leads
                await generate_leads(icp=cfg.CRAWLER_ICP, location=cfg.CRAWLER_LOCATION,
                                     count=5, owner="crawler")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await bus.emit("error", "crawler", f"crawl cycle error: {e}")
        await asyncio.sleep(max(60, cfg.CRAWLER_INTERVAL_MIN * 60))


async def reweave_loop():
    from .obsidian.weave import reweave
    await bus.emit("system", "reweave", f"auto-reweave online ({cfg.REWEAVE_INTERVAL_MIN}m)")
    while True:
        await asyncio.sleep(max(120, cfg.REWEAVE_INTERVAL_MIN * 60))
        try:
            stats = await asyncio.to_thread(reweave)
            await bus.emit("system", "reweave", f"nodes reconnected: {stats}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await bus.emit("error", "reweave", f"reweave error: {e}")


def start_background():
    if cfg.CRAWLER_ENABLED and cfg.CRAWLER_QUERIES:
        _tasks.append(asyncio.create_task(crawl_loop()))
    if cfg.REWEAVE_INTERVAL_MIN > 0:
        _tasks.append(asyncio.create_task(reweave_loop()))
    if cfg.SKILL_HARVEST_ENABLED and cfg.SKILL_REPOS:
        from .skills_harvester import harvest_loop
        _tasks.append(asyncio.create_task(harvest_loop()))
    if cfg.SECURITY_AUDIT_ENABLED:
        from .security_watch import security_loop
        _tasks.append(asyncio.create_task(security_loop()))
    return len(_tasks)


def stop_background():
    for t in _tasks:
        t.cancel()
    _tasks.clear()
