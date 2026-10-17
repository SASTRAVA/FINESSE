"""Deterministic conjunction router with an optional LangGraph runtime adapter."""
from __future__ import annotations

from typing import Any, TypedDict

SUBGRAPHS = (
    "consulting_lsd_graph", "sales_automation_graph",
    "udp_universal_workflow_graph", "security_toolchain_graph",
    "repo_capability_certification_graph", "evolving_memory_reflexion_graph",
)
STAGES = ("LISTEN", "SHAPE", "DELIVER", "VERIFY", "MEMORIZE")


class PlatformGraphState(TypedDict, total=False):
    tenant_id: str
    actor_sub: str
    actor_role: str
    allowed_lanes: list[str]
    sensitivity: str
    tainted: bool
    gatekeeper_nonce: str
    directive: str
    parsed_intent: str
    stage: str
    selected_subgraphs: list[str]
    tool_calls: list[dict]
    subgraph_outputs: dict[str, dict]
    memory_patterns: list[str]
    confidence_score: float
    audit_trail: list[dict]
    final_response: str


def _intent(directive: str, requested: list[str] | None) -> list[str]:
    if requested:
        invalid = set(requested) - set(SUBGRAPHS)
        if invalid:
            raise ValueError("unknown conjunction subgraph")
        return list(dict.fromkeys(requested))
    text = directive.casefold()
    selected = []
    rules = (
        ("consulting", ("consult", "listen", "shape", "deliver", "strategy")),
        ("sales", ("lead", "campaign", "email", "sales", "call")),
        ("udp", ("workflow", "automate", "primitive", "profession")),
        ("security", ("security", "scan", "vulnerability", "authorized")),
        ("repo", ("repository", "catalog", "certif", "adapter")),
        ("memory", ("memory", "learn", "pattern", "macro")),
    )
    for key, needles in rules:
        if any(needle in text for needle in needles):
            selected.append(key)
    if len(selected) > 1:
        return list(SUBGRAPHS)
    selected.append("consulting" if not selected else selected[0])
    key = selected[0]
    return [name for name in SUBGRAPHS if (
        name.startswith("consulting") if key == "consulting" else
        name.startswith("sales") if key == "sales" else
        name.startswith("udp") if key == "udp" else
        name.startswith("security") if key == "security" else
        name.startswith("repo") if key == "repo" else
        name.startswith("evolving") if key == "memory" else False)]


def _stage(name: str, selected: list[str], state: PlatformGraphState) -> dict:
    """Subgraph planning is deliberately side-effect free; providers require separate approval."""
    descriptions = {
        "consulting_lsd_graph": "Prepare a Listen-Shape-Deliver consulting workflow.",
        "sales_automation_graph": "Prepare sandbox-only lead, email, and explicit-call actions.",
        "udp_universal_workflow_graph": "Select parameterized workflow primitives for review.",
        "security_toolchain_graph": "Plan an authorized, non-destructive security assessment.",
        "repo_capability_certification_graph": "Evaluate repository evidence through certification gates.",
        "evolving_memory_reflexion_graph": "Review tenant- and lane-scoped patterns for corroboration.",
    }
    return {"status": "planned", "description": descriptions[name],
            "requires_human_approval": name in {
                "sales_automation_graph", "security_toolchain_graph",
                "repo_capability_certification_graph"},
            "tenant_id": state.get("tenant_id", "default")}


class _NativeCompiledGraph:
    async def ainvoke(self, state: PlatformGraphState) -> PlatformGraphState:
        current = dict(state)
        directive = str(current.get("directive", "")).strip()
        if not directive:
            raise ValueError("directive is required")
        current["stage"] = "LISTEN"
        chosen = _intent(directive, current.get("selected_subgraphs"))
        current["parsed_intent"] = current.get("parsed_intent") or " ".join(chosen)
        current["selected_subgraphs"] = chosen
        current["audit_trail"] = list(current.get("audit_trail", []))
        current["audit_trail"].append({"stage": "LISTEN", "selected": chosen})
        current["stage"] = "SHAPE"
        current["subgraph_outputs"] = {
            name: _stage(name, chosen, current) for name in chosen
        }
        current["stage"] = "DELIVER"
        current["final_response"] = (
            "Prepared a reviewable plan for: " + ", ".join(chosen)
            + ". No external side effects were executed.")
        current["stage"] = "VERIFY"
        current["audit_trail"].append({"stage": "VERIFY", "tainted": bool(current.get("tainted"))})
        current["stage"] = "MEMORIZE"
        current["confidence_score"] = float(current.get("confidence_score", 0.6))
        return current  # type: ignore[return-value]


class LangGraphConjunctionEngine:
    """Use LangGraph when it is installed; retain deterministic native behavior otherwise."""

    def __init__(self):
        self.backend = "native"
        self._graph = _NativeCompiledGraph()
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:
            return
        builder = StateGraph(PlatformGraphState)

        async def run_state(state: dict) -> dict:
            return await _NativeCompiledGraph().ainvoke(state)

        builder.add_node("conjunction_runtime", run_state)
        builder.add_edge(START, "conjunction_runtime")
        builder.add_edge("conjunction_runtime", END)
        self._graph = builder.compile()
        self.backend = "langgraph"

    async def ainvoke(self, state: PlatformGraphState) -> PlatformGraphState:
        return await self._graph.ainvoke(state)

    async def run(self, *, directive: str, actor_sub: str, actor_role: str,
                  tenant_id: str = "default", allowed_lanes: list[str] | None = None,
                  sensitivity: str = "internal", tainted: bool = False,
                  selected_subgraphs: list[str] | None = None) -> PlatformGraphState:
        if sensitivity not in {"public", "internal", "confidential", "restricted"}:
            raise ValueError("invalid sensitivity")
        return await self.ainvoke({
            "tenant_id": tenant_id, "actor_sub": actor_sub, "actor_role": actor_role,
            "allowed_lanes": allowed_lanes or [], "sensitivity": sensitivity,
            "tainted": tainted, "directive": directive,
            "selected_subgraphs": selected_subgraphs or [],
        })


conjunction_engine = LangGraphConjunctionEngine()
