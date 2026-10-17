"""AgentSpec — the declarative identity of an agent type. No behavior here."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AgentSpec:
    key: str                    # short id, e.g. "coding"
    title: str                  # human title, e.g. "Coding Agent"
    lane: str                   # rbac lane: coding | prompt | marketing | bizdev | exec | general
    model_role: str             # which model tier in config.MODELS
    system_prompt: str
    temperature: float = 0.3
    max_tokens: int = 1400
    learns: bool = True         # contributes patterns to shared memory
    base_confidence: float = 0.75
    spawnable: bool = True      # can the orchestrator spin up parallel copies?
    uses_tools: bool = False    # only tool-benefiting agents pay the tool-calling latency
    agentic: bool = True        # run the autonomous plan->act->reflect loop (off for planner)
