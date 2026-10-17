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
from ..auth.security import verify_gatekeeper_approval
from ..prompt_guard import is_untrusted_source, wrap_untrusted_content

_AUDIT = cfg.DATA / "audit.jsonl"


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    needs_human: bool = False           # True for proposed (unexecuted) write actions
    proposed_action: dict | None = None
    tainted: bool = False
    sensitivity: str = "public"

    def to_message(self) -> str:
        if self.needs_human:
            return ("PROPOSED ACTION (requires human approval, NOT executed): "
                    + json.dumps(self.proposed_action))
        if not self.ok:
            error = self.error or "unspecified tool failure"
            return ("TOOL ERROR: " + wrap_untrusted_content(error, "external_tool")
                    if self.tainted else f"TOOL ERROR: {error}")
        value = json.dumps(self.data) if not isinstance(self.data, str) else self.data
        value = value[:4000]
        return wrap_untrusted_content(value, "external_tool") if self.tainted else value


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
                       approve_writes: bool = False, tainted: bool = False,
                       approval_token: str = "", user_id: str = "",
                       user_role: str = "") -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(False, error=f"unknown tool: {name}")
        if not tool.allowed(lane):
            self._audit(name, args, lane, actor, "denied")
            return ToolResult(False, error=f"lane '{lane}' may not use '{name}'")
        approved = verify_gatekeeper_approval(approval_token, actor, name, args)
        if tainted and tool.write and not approved:
            self._audit(name, args, lane, actor, "blocked:tainted")
            return ToolResult(False, error="tainted context requires a verified Gatekeeper approval",
                              tainted=True)
        # human-gate: writes never auto-execute unless explicitly approved by a human
        if tool.write and not (approve_writes or approved):
            self._audit(name, args, lane, actor, "proposed")
            return ToolResult(True, needs_human=True,
                              proposed_action={"tool": name, "args": args})
        try:
            kwargs = dict(args)
            if "lane" in inspect.signature(tool.run).parameters:
                kwargs["lane"] = lane
            if "user_id" in inspect.signature(tool.run).parameters:
                kwargs["user_id"] = user_id or actor
            if "user_role" in inspect.signature(tool.run).parameters:
                kwargs["user_role"] = user_role or lane
            res = await tool.run(**kwargs)
            res.tainted = tainted or is_untrusted_source(name)
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
