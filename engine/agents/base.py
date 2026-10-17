"""
Base agent — the single "instrument" in the orchestra.

An agent is deliberately tiny (Karpathy rule): a spec (identity + system prompt
+ lane + model role) plus a `run()` that does retrieve -> think -> (optionally
learn). Everything heavy is delegated to shared services (llm, retriever,
memory, bus), so spawning a thousand agents costs almost nothing until they run.
"""
from __future__ import annotations
import time
import uuid
from dataclasses import dataclass, field

from ..llm import llm
from ..rag import retriever
from .base_types import AgentSpec  # forward (defined in registry via re-export)


@dataclass
class AgentResult:
    agent_id: str
    role: str
    output: str
    elapsed: float
    confidence: float = 0.7
    steps: int = 1


_AGENTIC_PREAMBLE = (
    "\n\nYou are an AUTONOMOUS agent. Work in a loop: plan, then take the next step. "
    "Call a tool whenever it would give you real information — search the brain, the web, "
    "or code repos rather than guessing. Observe each result and decide the next step. "
    "When (and only when) the task is fully handled, give your finished deliverable. "
    "FAITHFULNESS RULE: use ONLY facts you were given or that tools returned — never invent "
    "companies, names, contacts, numbers, or data. If something is unknown, say so. "
    "Keep the human in the loop: end with a short 'Needs human review:' note.")


class Agent:
    def __init__(self, spec: "AgentSpec", trace: str = ""):
        self.spec = spec
        self.id = f"{spec.key}-{uuid.uuid4().hex[:6]}"
        self.trace = trace

    async def run(self, task: str, *, context_query: str | None = None,
                  extra_context: str = "") -> AgentResult:
        from ..orchestra.events import bus
        from ..orchestra.memory import shared_memory

        from ..config import cfg
        from ..mcp import mcp

        t0 = time.time()
        await bus.emit("spawn", self.id, f"{self.spec.title} online", trace=self.trace,
                       lane=self.spec.lane, role=self.spec.key)

        ctx = await retriever.context(context_query or task, role=self.spec.lane, limit=5)
        await bus.emit("think", self.id, "retrieved brain context, planning…", trace=self.trace)

        system = self.spec.system_prompt + (_AGENTIC_PREAMBLE if self.spec.agentic else "")
        user = (f"# Task\n{task}\n\n"
                f"# Relevant brain context (retrieved)\n{ctx}\n"
                f"{('# Additional context\n' + extra_context) if extra_context else ''}\n\n"
                f"Act as the {self.spec.title}. Be concrete and production-grade.")

        tool_schemas = mcp.schemas(self.spec.lane) if self.spec.uses_tools else []
        online = llm.backend_name() != "offline-stub"
        steps = 1

        async def _on_step(n: int, kind: str, detail: str):
            emap = {"act": "tool", "observe": "think", "think": "think"}
            await bus.emit(emap.get(kind, "think"), self.id, f"step {n}: {detail}",
                           trace=self.trace)

        if online and self.spec.agentic:
            async def _dispatch(name: str, args: dict) -> str:
                res = await mcp.dispatch(name, args, lane=self.spec.lane, actor=self.id)
                return res.to_message()
            output, steps = await llm.agentic_loop(
                system, user, role=self.spec.model_role, tool_schemas=tool_schemas,
                dispatch=_dispatch, on_step=_on_step, temperature=self.spec.temperature,
                max_tokens=self.spec.max_tokens, max_steps=cfg.AGENTIC_MAX_STEPS,
                lane=self.spec.lane)
            # self-reflection pass (Claude-style critique + improve)
            if cfg.AGENTIC_REFLECT and self.spec.learns:
                await bus.emit("think", self.id, "reflecting & self-critiquing draft…",
                               trace=self.trace)
                output = await llm.reflect(system, task, output, role=self.spec.model_role,
                                           max_tokens=self.spec.max_tokens, lane=self.spec.lane)
                steps += 1
        else:
            output = await llm.chat(system, user, role=self.spec.model_role,
                                    temperature=self.spec.temperature,
                                    max_tokens=self.spec.max_tokens)

        elapsed = time.time() - t0
        await bus.emit("done", self.id,
                       f"{self.spec.title} finished in {elapsed:.1f}s ({steps} steps)",
                       trace=self.trace, chars=len(output), steps=steps)

        # contribute a distilled pattern back to the shared consciousness
        if self.spec.learns and len(output) > 200:
            headline = output.strip().split("\n", 1)[0][:300]
            await shared_memory.learn_pattern(
                pattern=f"[{self.spec.title}] {headline}",
                role=self.spec.lane, actor=self.id, trace=self.trace)

        return AgentResult(self.id, self.spec.key, output, elapsed,
                           self.spec.base_confidence, steps=steps)
