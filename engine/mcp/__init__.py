"""
MCP tool layer — the agents' hands.

A Tool is a small async capability an agent can call. The registry:
  - RBAC-gates tools by lane (mirrors vault Security/Role-Based Access),
  - AUDIT-logs every call (mirrors vault Logging/Audit Logs),
  - HUMAN-GATES writes: an action tool never executes on its own — it returns a
    *proposed action* for a person to approve. Reads run freely.

Starter connectors (this pass):
  vault_search  — local RAG over the brain        (keyless, read, all lanes)
  web_search    — fresh web results               (keyless, read, marketing/bizdev/general)
  github_*      — code search / read / issue       (token, read + human-gated write, coding)

Add more from vault/16_MCP by dropping a Tool subclass in connectors/ and registering it.
"""
from .base import Tool, ToolResult, ToolRegistry, mcp
from . import connectors  # noqa: F401  (registers built-in tools on import)

__all__ = ["Tool", "ToolResult", "ToolRegistry", "mcp"]
