"""
Swarm — runs a set of agents concurrently.

The agents fire in parallel via asyncio.gather; actual inference pressure is
bounded globally by TurboQuant's semaphore, so "30 users x a swarm each" degrades
gracefully (queued) instead of collapsing. One failed agent never sinks the swarm.
"""
from __future__ import annotations
import asyncio
from ..agents.base import AgentResult
from .events import bus
from ..prompt_guard import UNTRUSTED_DATA_POLICY
from ..llm.provider import DataEgressBlocked


class Swarm:
    async def run(self, agents_and_tasks: list[tuple], trace: str = "",
                  *, user_id: str = "", user_role: str = "",
                  sensitivity: str = "internal", tenant_id: str = "default") -> list[AgentResult]:
        """agents_and_tasks: list of (Agent, task_str)."""
        await bus.emit("system", "swarm", f"launching swarm of {len(agents_and_tasks)} agents",
                       trace=trace)

        async def _one(agent, task):
            try:
                return await agent.run(f"{UNTRUSTED_DATA_POLICY}\n\n{task}",
                                       user_id=user_id, user_role=user_role,
                                       sensitivity=sensitivity, tenant_id=tenant_id)
            except Exception as e:  # noqa: BLE001
                if isinstance(e, DataEgressBlocked):
                    raise
                await bus.emit("error", agent.id, f"agent failed: {e}", trace=trace)
                return AgentResult(agent.id, agent.spec.key,
                                   f"[agent error: {e}]", 0.0, 0.0)

        results = await asyncio.gather(*[_one(a, t) for a, t in agents_and_tasks])
        await bus.emit("system", "swarm", f"swarm complete ({len(results)} results)", trace=trace)
        return list(results)


swarm = Swarm()
