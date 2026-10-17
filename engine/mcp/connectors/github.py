"""
github_* — GitHub connector for the coding lane.
Reads run freely (needs GITHUB_TOKEN for private/rate-limits). The write tool
(create issue) is HUMAN-GATED: it returns a proposed action, never auto-executes.
"""
from __future__ import annotations
import os
from ..base import Tool, ToolResult, mcp

_API = "https://api.github.com"


def _headers():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    h = {"Accept": "application/vnd.github+json", "User-Agent": "SastravaFinesse"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


class GitHubSearchCode(Tool):
    name = "github_search_code"
    description = "Search code across GitHub (or a repo with 'repo:owner/name' in the query)."
    lanes = ("coding", "exec")
    write = False
    params = {"type": "object",
              "properties": {"query": {"type": "string"}},
              "required": ["query"]}

    async def run(self, query: str) -> ToolResult:
        import httpx
        async with httpx.AsyncClient(timeout=15, headers=_headers()) as c:
            r = await c.get(f"{_API}/search/code", params={"q": query, "per_page": 5})
        if r.status_code == 401:
            return ToolResult(False, error="set GITHUB_TOKEN for code search")
        if r.status_code >= 400:
            return ToolResult(False, error=f"github {r.status_code}: {r.text[:150]}")
        items = [{"repo": it["repository"]["full_name"], "path": it["path"],
                  "url": it["html_url"]} for it in r.json().get("items", [])]
        return ToolResult(True, data=items)


class GitHubReadFile(Tool):
    name = "github_read_file"
    description = "Read a file's contents from a public GitHub repo."
    lanes = ("coding", "exec")
    write = False
    params = {"type": "object",
              "properties": {"repo": {"type": "string", "description": "owner/name"},
                             "path": {"type": "string"},
                             "ref": {"type": "string", "description": "branch/tag, default main"}},
              "required": ["repo", "path"]}

    async def run(self, repo: str, path: str, ref: str = "main") -> ToolResult:
        import httpx, base64
        async with httpx.AsyncClient(timeout=15, headers=_headers()) as c:
            r = await c.get(f"{_API}/repos/{repo}/contents/{path}", params={"ref": ref})
        if r.status_code >= 400:
            return ToolResult(False, error=f"github {r.status_code}")
        content = r.json().get("content", "")
        try:
            text = base64.b64decode(content).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            text = "(binary or undecodable)"
        return ToolResult(True, data={"repo": repo, "path": path, "text": text[:6000]})


class GitHubCreateIssue(Tool):
    name = "github_create_issue"
    description = "Propose creating a GitHub issue (requires human approval before it is created)."
    lanes = ("coding", "exec")
    write = True   # <-- human-gated: dispatch returns a proposal, does not create
    params = {"type": "object",
              "properties": {"repo": {"type": "string", "description": "owner/name"},
                             "title": {"type": "string"}, "body": {"type": "string"}},
              "required": ["repo", "title"]}

    async def run(self, repo: str, title: str, body: str = "") -> ToolResult:
        # Only reached when a human has approved (approve_writes=True in dispatch).
        import httpx
        async with httpx.AsyncClient(timeout=15, headers=_headers()) as c:
            r = await c.post(f"{_API}/repos/{repo}/issues", json={"title": title, "body": body})
        if r.status_code >= 400:
            return ToolResult(False, error=f"github {r.status_code}: {r.text[:150]}")
        return ToolResult(True, data={"created": r.json().get("html_url")})


for _t in (GitHubSearchCode(), GitHubReadFile(), GitHubCreateIssue()):
    mcp.register(_t)
