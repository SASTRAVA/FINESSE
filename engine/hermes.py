"""
HERMES — the overseer meta-agent that closes the self-evolving loop.

Hermes does not do departmental work. It WATCHES every agentic loop and swarm,
and after each interaction it asks: "what capability did we lack?" Then it acts:

  1. MONITOR   — observe(directive, deliverable, agents) after every run.
  2. ANALYZE   — an LLM gap-analysis: which skills were missing, what to search
                 GitHub for, and whether a NEW agent type is warranted.
  3. EVOLVE    — pull skills from the top-starred public repo for each gap
                 (into the shared brain), and register new agent types on the fly.

The result: every interaction can make the whole ecosystem a little more capable.
Guardrails: rate-limited, capped new-agents/cycle, deduped, everything logged to
the bus + vault so a human can see (and prune) what Hermes added.
"""
from __future__ import annotations
import json
import re
import time
import asyncio

from .config import cfg

_LANES = {"coding", "prompt", "marketing", "bizdev", "exec", "general"}

_ANALYZE_SYS = (
    "You are HERMES, the overseer of an AI agent orchestra. Given a completed task, "
    "its deliverable, and which agents handled it, judge what capability the system "
    "LACKED that would have made this better. Be conservative — only flag real gaps. "
    "Return ONLY JSON: {\"missing_skills\":[\"short topic\",...], "
    "\"github_queries\":[\"search terms for a skills/prompts repo\",...], "
    "\"new_agent\":{\"title\":\"..\",\"lane\":\"coding|prompt|marketing|bizdev|general\","
    "\"mandate\":\"one sentence\"}|null}. Empty arrays / null when nothing is needed.")


class Hermes:
    def __init__(self):
        self.stats = {"observations": 0, "skills_added": 0, "agents_created": 0,
                      "repos_harvested": 0, "gaps_seen": 0}
        self.log: list[dict] = []
        self._last_evolve = 0.0
        self._lock = asyncio.Lock()

    def _note(self, kind: str, detail: str):
        self.log.append({"ts": time.time(), "kind": kind, "detail": detail})
        self.log = self.log[-60:]

    async def observe(self, *, directive: str, deliverable: str, agents: list[str],
                      trace: str = "") -> None:
        """Called (in the background) after every directive / swarm / single-agent run."""
        if not cfg.HERMES_ENABLED:
            return
        from .orchestra.events import bus
        self.stats["observations"] += 1
        await bus.emit("system", "hermes",
                       f"overseeing interaction — {len(agents)} agent(s): {', '.join(agents) or '—'}",
                       trace=trace)
        try:
            gaps = await self._analyze(directive, deliverable, agents)
        except Exception as e:  # noqa: BLE001
            await bus.emit("error", "hermes", f"analysis failed: {e}", trace=trace)
            return
        if gaps:
            await self._evolve(gaps, trace)

    async def _analyze(self, directive, deliverable, agents) -> dict | None:
        from .llm import llm
        user = (f"Task: {directive}\n\nAgents used: {agents}\n\n"
                f"Deliverable (excerpt):\n{(deliverable or '')[:1400]}\n\nReturn JSON only.")
        raw = await llm.chat(_ANALYZE_SYS, user, role="fast", temperature=0.2, max_tokens=400)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None

    async def _evolve(self, gaps: dict, trace: str) -> None:
        from .orchestra.events import bus
        from .skills_harvester import search_repos, harvest_repo
        from .agents.registry import registry

        queries = [q for q in (gaps.get("github_queries") or []) if q][:2]
        new_agent = gaps.get("new_agent")
        if not queries and not new_agent:
            return

        async with self._lock:
            now = time.time()
            if now - self._last_evolve < cfg.HERMES_MIN_INTERVAL_S:
                self._note("throttle", "evolution rate-limited")
                return
            self._last_evolve = now
            self.stats["gaps_seen"] += 1

            # 1) discover + harvest skills from the top-starred repo per gap
            for q in queries:
                try:
                    repos = await search_repos(q, min_stars=cfg.HERMES_MIN_STARS, limit=3)
                    if not repos:
                        continue
                    top = repos[0]
                    await bus.emit("learn", "hermes",
                                   f"gap '{q}' → harvesting {top['full_name']} (★{top['stars']})",
                                   trace=trace)
                    added = await harvest_repo(top["full_name"], actor="hermes", max_files=20)
                    self.stats["skills_added"] += added
                    self.stats["repos_harvested"] += 1
                    self._note("harvest", f"{top['full_name']} (+{added} skills) for '{q}'")
                except Exception as e:  # noqa: BLE001
                    await bus.emit("error", "hermes", f"harvest '{q}': {e}", trace=trace)

            # 2) grow a new agent type if a real, non-duplicate gap exists
            if new_agent and isinstance(new_agent, dict) and self.stats.get("_this_cycle", 0) < 999:
                created = 0
                title = (new_agent.get("title") or "").strip()
                lane = new_agent.get("lane") if new_agent.get("lane") in _LANES else "general"
                mandate = new_agent.get("mandate") or ""
                if title and created < cfg.HERMES_MAX_NEW_AGENTS and not self._exists(title, registry):
                    spec = registry.register_from_injection(
                        title=title, lane=lane, mandate=mandate,
                        model_role="coding" if lane == "coding" else "fast")
                    self.stats["agents_created"] += 1
                    self._note("agent", f"created '{spec.title}' ({lane})")
                    await bus.emit("spawn", "hermes",
                                   f"new agent joined the orchestra: {spec.title} ({lane})",
                                   trace=trace, lane=lane)

    @staticmethod
    def _exists(title: str, registry) -> bool:
        t = title.lower().replace(" agent", "").strip()
        return any(t and t in s.title.lower() for s in registry.all())


hermes = Hermes()
