"""
web_search — fresh web results. Keyless (DuckDuckGo HTML), best-effort, read-only.
Available to marketing / bizdev / general lanes (fresh market/company data).
"""
from __future__ import annotations
import re
import html
from ..base import Tool, ToolResult, mcp


class WebSearch(Tool):
    name = "web_search"
    description = ("Search the public web for fresh, external information (market trends, "
                   "competitors, companies, news). Read-only. Use when the brain lacks "
                   "current external facts.")
    lanes = ("marketing", "bizdev", "general", "exec")
    write = False
    params = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "description": "default 5"},
        },
        "required": ["query"],
    }

    async def run(self, query: str, max_results: int = 5) -> ToolResult:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; SastravaFinesse/0.1)"}) as c:
                r = await c.post("https://html.duckduckgo.com/html/", data={"q": query})
            results = self._parse(r.text, int(max_results or 5))
            if not results:
                return ToolResult(True, data=[], error="no results parsed")
            return ToolResult(True, data=results)
        except Exception as e:  # noqa: BLE001
            return ToolResult(False, error=f"web_search unavailable: {e}")

    @staticmethod
    def _parse(text: str, n: int) -> list[dict]:
        # DuckDuckGo HTML result anchors
        out = []
        for m in re.finditer(r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', text, re.DOTALL):
            url, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            out.append({"title": html.unescape(title).strip(), "url": html.unescape(url)})
            if len(out) >= n:
                break
        return out


mcp.register(WebSearch())
