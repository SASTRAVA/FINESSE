"""MCP core: Tool, ToolResult, and the RBAC + audit + human-gate registry."""
from __future__ import annotations
import abc
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import cfg

_AUDIT = cfg.DATA / "audit.jsonl"


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    needs_human: bool = False           # True for proposed (unexecuted) write actions
    proposed_action: dict | None = None

    def to_message(self) -> str:
        if self.needs_human:
            return ("PROPOSED ACTION (requires human approval, NOT executed): "
                    + json.dumps(self.proposed_action))
        if not self.ok:
            return f"TOOL ERROR: {self.error}"
        return json.dumps(self.data)[:4000] if not isinstance(self.data, str) else self.data[:4000]


class Tool(abc.ABC):
    name: str = "tool"
    description: str = ""
    lanes: tuple[str, ...] = ("*",)      # which agent lanes may call it
    write: bool = False                  # write/action tools are human-gated
    params: dict = {"type": "object", "properties": {}, "required": []}

    def allowed(self, lane: str) -> bool:
        return "*" in self.lanes or lane in self.lanes

    @abc.abstractmethod
    async def run(self, **kwargs) -> ToolResult: ...

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.params}}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def for_lane(self, lane: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.allowed(lane)]

    def schemas(self, lane: str) -> list[dict]:
        return [t.schema() for t in self.for_lane(lane)]

    async def dispatch(self, name: str, args: dict, *, lane: str, actor: str,
                       approve_writes: bool = False) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, error=f"unknown tool: {name}")
        if not tool.allowed(lane):
            self._audit(name, args, lane, actor, "denied")
            return ToolResult(False, error=f"lane '{lane}' may not use '{name}'")
        # human-gate: writes never auto-execute unless explicitly approved by a human
        if tool.write and not approve_writes:
            self._audit(name, args, lane, actor, "proposed")
            return ToolResult(True, needs_human=True,
                              proposed_action={"tool": name, "args": args})
        try:
            kwargs = dict(args)
            if "lane" in inspect.signature(tool.run).parameters:
                kwargs["lane"] = lane
            res = await tool.run(**kwargs)
            self._audit(name, args, lane, actor, "ok" if res.ok else "error")
            return res
        except Exception as e:  # noqa: BLE001
            self._audit(name, args, lane, actor, f"exception:{e}")
            return ToolResult(False, error=str(e))

    @staticmethod
    def _audit(name, args, lane, actor, outcome):
        try:
            _AUDIT.parent.mkdir(parents=True, exist_ok=True)
            with _AUDIT.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "tool": name, "lane": lane,
                                    "actor": actor, "outcome": outcome,
                                    "args": {k: str(v)[:120] for k, v in args.items()}}) + "\n")
        except Exception:  # noqa: BLE001
            pass


mcp = ToolRegistry()
