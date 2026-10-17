"""
Orchestrator — the conductor (CEO-level, Layer 0 of the Harness Method).

Flow for one directive:
  1. PLAN     — a Planner agent picks the minimum swarm of agents + their tasks.
                (Bounded by the requester's lane/permissions.)
  2. SWARM    — those agents run concurrently, each retrieving from the shared brain.
  3. SYNTH    — a Synthesizer merges everything into one human-facing deliverable.
  4. PERSIST  — the deliverable is written to the vault (Obsidian live map) and a
                distilled pattern is folded into shared memory.

Human-in-the-loop: the orchestrator NEVER executes external actions. It produces
a deliverable that ends with a human-review checklist. The human decides.
"""
from __future__ import annotations
import asyncio
import json
import re
import time
import uuid

from ..config import cfg
from ..agents.registry import registry
from ..auth.rbac import can, role_of
from .events import bus
from .memory import shared_memory
from .swarm import swarm
from .sessions import sessions
from ..obsidian.mapper import write_deliverable


# Hard cap on agents raised per directive — prevents the "everything fired" blowups
# and keeps latency/cost bounded. Users can still force more via preferred_agents.
_MAX_AGENTS_PER_DIRECTIVE = 4


def _lanes_allowed(user_role: str) -> list[str]:
    r = role_of(user_role)
    if "*" in r.permissions or "spawn:any" in r.permissions:
        return ["coding", "prompt", "marketing", "bizdev", "exec", "general", "security"]
    lanes = {r.lane, "general"}
    for p in r.permissions:
        if p.startswith("spawn:"):
            lanes.add(p.split(":", 1)[1])
    return list(lanes)


class Orchestrator:
    async def run_directive(self, directive: str, *, user_email: str, user_role: str,
                            preferred_agents: list[str] | None = None,
                            all_agents: bool = False) -> dict:
        trace = uuid.uuid4().hex[:8]
        t0 = time.time()
        session = sessions.start("swarm", directive, trace, requested_by=user_role)
        allowed = _lanes_allowed(user_role)
        await bus.emit("system", "orchestrator",
                       f"directive received from {user_role}", trace=trace,
                       directive=directive[:200], lanes=allowed)

        # candidate agents the requester is allowed to raise
        candidates = [s for s in registry.all()
                      if s.lane in allowed and s.key not in ("orchestrator_planner", "synth")]
        roster = [{"key": s.key, "title": s.title, "lane": s.lane} for s in candidates]

        # "activate all swarms": fire every agent the requester is allowed to raise
        if all_agents:
            preferred_agents = [s.key for s in candidates]
        forced = bool(preferred_agents)   # user explicitly chose -> bypass the planner cap

        plan = await self._plan(directive, roster, trace, preferred_agents)

        # Validate the plan against the REAL roster — the planner (a small model)
        # sometimes invents keys. Keep only real ones; else fall back to a keyword
        # heuristic that picks 1-3 RELEVANT agents (never "run everything").
        valid_keys = {s.key for s in candidates}
        chosen, seen = [], set()
        for item in plan.get("agents", []):
            k = item.get("key", "")
            if k in valid_keys and k not in seen:
                seen.add(k)
                chosen.append({"key": k, "task": item.get("task", directive)})
        if not chosen:
            chosen = [{"key": k, "task": directive}
                      for k in self._heuristic_agents(directive, candidates)]
        # cap only planner-chosen swarms; respect explicit user/all-swarm selections
        cap = cfg.SWARM_MAX_AGENTS if forced else _MAX_AGENTS_PER_DIRECTIVE
        chosen = chosen[:cap]
        await bus.emit("system", "orchestrator",
                       f"selected {len(chosen)} agent(s): {[c['key'] for c in chosen]}", trace=trace)

        # 2. SWARM
        agents_and_tasks = []
        for item in chosen:
            spec = registry.get(item["key"])
            if spec is None or spec.lane not in allowed:
                continue
            agent = registry.spawn(spec.key, trace=trace)
            agents_and_tasks.append((agent, item.get("task", directive)))
        results = await swarm.run(agents_and_tasks, trace=trace)

        # 3. SYNTH — skip the extra LLM call when a single agent already answered
        if len(results) == 1:
            final = results[0].output
            await bus.emit("system", "orchestrator", "single agent — synthesis skipped", trace=trace)
        else:
            final = await self._synthesize(directive, results, trace)

        # 4. PERSIST — off the event loop (sync file write + Obsidian REST push, F3)
        note_path = await asyncio.to_thread(write_deliverable, directive, final, user_role,
                                            trace, [r.role for r in results])
        await shared_memory.remember(text=final[:1500], kind="deliverable", role=user_role,
                                     actor="orchestrator", trace=trace, confidence=0.7)

        elapsed = time.time() - t0
        sessions.finish(session, agents=[r.role for r in results], elapsed=elapsed,
                        preview=final)
        await bus.emit("done", "orchestrator", f"directive complete in {elapsed:.1f}s",
                       trace=trace, agents=len(results))
        # Hermes observes every interaction (background — never blocks the response)
        if cfg.HERMES_ENABLED:
            from ..hermes import hermes
            asyncio.create_task(hermes.observe(directive=directive, deliverable=final,
                                               agents=[r.role for r in results], trace=trace))
        return {
            "trace": trace,
            "directive": directive,
            "plan": plan,
            "agents": [{"id": r.agent_id, "role": r.role, "elapsed": round(r.elapsed, 2),
                        "steps": r.steps, "output": r.output} for r in results],
            "deliverable": final,
            "vault_note": note_path,
            "elapsed": round(elapsed, 2),
        }

    async def run_single_agent(self, agent_key: str, task: str, *, user_role: str) -> dict:
        """Drive ONE agent directly (the 'use agents one by one' path). No planner/synth."""
        trace = uuid.uuid4().hex[:8]
        t0 = time.time()
        spec = registry.get(agent_key)
        if spec is None:
            raise KeyError(f"unknown agent: {agent_key}")
        allowed = _lanes_allowed(user_role)
        if spec.lane not in allowed:
            raise PermissionError(f"role '{user_role}' may not run '{agent_key}'")
        session = sessions.start("single", f"[{spec.title}] {task}", trace,
                                 requested_by=user_role)
        agent = registry.spawn(agent_key, trace=trace)
        result = await agent.run(task)
        note_path = await asyncio.to_thread(write_deliverable, f"[{spec.title}] {task}",
                                            result.output, user_role, trace, [result.role])
        elapsed = time.time() - t0
        sessions.finish(session, agents=[result.role], elapsed=elapsed, preview=result.output)
        if cfg.HERMES_ENABLED:
            from ..hermes import hermes
            asyncio.create_task(hermes.observe(directive=f"[{spec.title}] {task}",
                                               deliverable=result.output, agents=[result.role],
                                               trace=trace))
        return {"trace": trace, "agent": spec.key, "title": spec.title, "lane": spec.lane,
                "output": result.output, "elapsed": round(elapsed, 2), "steps": result.steps,
                "vault_note": note_path}

    async def _plan(self, directive, roster, trace, preferred):
        if preferred:
            return {"agents": [{"key": k, "task": directive} for k in preferred],
                    "synthesis": "user-selected agents"}
        keys = [s["key"] for s in roster]
        planner = registry.spawn("orchestrator_planner", trace=trace)
        prompt = (f"Directive: {directive}\n\n"
                  f"Choose agents ONLY from this exact key list (do NOT invent keys):\n"
                  f"{keys}\n\nAgent details: {json.dumps(roster)}\n\n"
                  f"Pick the FEWEST agents (1-3) whose lanes actually match the directive. "
                  f'Return ONLY JSON: {{"agents":[{{"key":"<one of the keys>","task":"..."}}]}}')
        raw = await planner.run(prompt)
        return self._parse_json(raw.output) or {"agents": []}

    @staticmethod
    def _heuristic_agents(directive: str, candidates) -> list[str]:
        """Keyword-based lane picker used when the planner returns nothing valid."""
        d = directive.lower()
        wants = []
        if any(w in d for w in ("code", "python", "script", "function", "api", "bug",
                                "program", "sql", "app", "website", "deploy")):
            wants.append("coding")
        if any(w in d for w in ("market", "seo", "campaign", "post", "content", "brand",
                                "social", "ad ", "copy", "linkedin", "launch")):
            wants.append("marketing")
        if any(w in d for w in ("prompt", "instruction", "system message")):
            wants.append("prompt")
        if any(w in d for w in ("lead", "client", "prospect", "outreach", "sales", "crm",
                                "pipeline")):
            wants.append("bizdev")
        picked = []
        for lane in wants:
            core = next((s for s in candidates if s.lane == lane), None)
            if core:
                picked.append(core.key)
        if not picked:
            core = next((s for s in candidates if s.lane == "general"), None) \
                or (candidates[0] if candidates else None)
            if core:
                picked.append(core.key)
        return picked[:3]

    async def _synthesize(self, directive, results, trace):
        synth = registry.spawn("synth", trace=trace)
        joined = "\n\n".join(f"## {r.role} ({r.agent_id})\n{r.output}" for r in results)
        prompt = (f"Original directive: {directive}\n\nAgent outputs:\n{joined}\n\n"
                  f"Merge into one deliverable for a human.")
        return (await synth.run(prompt)).output

    @staticmethod
    def _parse_json(text: str):
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:  # noqa: BLE001
            return None


orchestrator = Orchestrator()
