"""vault_search — local RAG over the Sastrava brain, restricted to the caller's lane."""
from __future__ import annotations
from ..base import Tool, ToolResult, mcp
from ...rag.retriever import retriever


class VaultSearch(Tool):
    name = "vault_search"
    description = ("Search the caller's lane-scoped Sastrava knowledge brain (plus shared "
                   "memory) for relevant context. Use this before answering to ground yourself "
                   "in company knowledge.")
    lanes = ("*",)
    write = False
    params = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "what to look up in the brain"},
            "limit": {"type": "integer", "description": "max snippets (default 5)"},
        },
        "required": ["query"],
    }

    async def run(self, query: str, limit: int = 5, lane: str = "general",
                  user_id: str = "", user_role: str = "") -> ToolResult:
        hits = await retriever.retrieve(query, role=user_role or lane, lane=lane,
                                        user_id=user_id, limit=min(int(limit or 5), 10))
        data = [{"title": h["payload"].get("title"), "score": round(h["score"], 3),
                 "text": h["payload"].get("text", "")[:600]} for h in hits]
        order = ("public", "internal", "confidential", "restricted")
        sensitivity = max((h["payload"]["sensitivity"] for h in hits),
                          key=order.index, default="public")
        return ToolResult(True, data=data, sensitivity=sensitivity)


mcp.register(VaultSearch())
