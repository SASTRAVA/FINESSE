"""
Skill harvester — continuously pull skills from FREE GitHub repos into the brain.

For each configured "owner/repo" (or "owner/repo/sub/path"), it walks the tree,
pulls Markdown skill/prompt files, writes them into vault/06_Skills/_Harvested/
(so Obsidian maps them live), and indexes them into the shared brain so every
agent instantly retrieves them — keeping accuracy/precision climbing over time.

Keyless works (GitHub allows 60 req/hr unauthenticated); set GITHUB_TOKEN for
5000 req/hr. Opt-in via .env:
  SKILL_HARVEST_ENABLED=1
  SKILL_REPOS="f/awesome-prompts, org/agent-skills/skills"
Human-in-the-loop: harvested skills are KNOWLEDGE (retrievable context), not
auto-executed code. A human still decides how agents use them.
"""
from __future__ import annotations
import asyncio
import base64
import re
from pathlib import Path

from .config import cfg
from .rag.ingest import ingest_text
from .orchestra.events import bus

_API = "https://api.github.com"
_SKILLS = cfg.VAULT / "06_Skills" / "_Harvested"
_MAX_FILES_PER_REPO = 60
_SEEN = cfg.DATA / ".skills_seen.json"


def _load_seen() -> set:
    try:
        import json
        return set(json.loads(_SEEN.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def _save_seen(s: set) -> None:
    try:
        import json
        _SEEN.write_text(json.dumps(sorted(s)), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _headers():
    h = {"Accept": "application/vnd.github+json", "User-Agent": "SastravaFinesse"}
    if cfg.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {cfg.GITHUB_TOKEN}"
    return h


def _parse_spec(spec: str):
    parts = spec.strip("/").split("/")
    owner, repo = parts[0], parts[1]
    sub = "/".join(parts[2:]) if len(parts) > 2 else ""
    return owner, repo, sub


async def _list_md(client, owner, repo, sub) -> list[dict]:
    """Recursively collect .md files under sub (via the git tree API, one call)."""
    r = await client.get(f"{_API}/repos/{owner}/{repo}")
    if r.status_code >= 400:
        return []
    branch = r.json().get("default_branch", "main")
    t = await client.get(f"{_API}/repos/{owner}/{repo}/git/trees/{branch}",
                         params={"recursive": "1"})
    if t.status_code >= 400:
        return []
    out = []
    for node in t.json().get("tree", []):
        p = node.get("path", "")
        if node.get("type") == "blob" and p.lower().endswith(".md") and p.startswith(sub):
            out.append({"path": p, "url": node.get("url")})
        if len(out) >= _MAX_FILES_PER_REPO:
            break
    return out


async def search_repos(query: str, min_stars: int = 400, limit: int = 3) -> list[dict]:
    """Find high-star public repos for a topic (used by Hermes to discover skills)."""
    import httpx
    q = f"{query} stars:>={min_stars}"
    async with httpx.AsyncClient(timeout=20, headers=_headers()) as c:
        r = await c.get(f"{_API}/search/repositories",
                        params={"q": q, "sort": "stars", "order": "desc", "per_page": limit})
    if r.status_code >= 400:
        return []
    return [{"full_name": it["full_name"], "stars": it.get("stargazers_count", 0),
             "desc": (it.get("description") or "")[:120]} for it in r.json().get("items", [])]


async def harvest_repo(spec: str, *, actor: str = "skill_harvester", max_files: int = 30) -> int:
    """Harvest one repo's markdown skills into the brain + vault. Returns count."""
    import httpx
    _SKILLS.mkdir(parents=True, exist_ok=True)
    added = 0
    owner, repo, sub = _parse_spec(spec)
    seen = _load_seen()
    async with httpx.AsyncClient(timeout=25, headers=_headers()) as client:
        files = (await _list_md(client, owner, repo, sub))[:max_files]
        for f in files:
            try:
                blob = await client.get(f["url"])
                if blob.status_code >= 400:
                    continue
                text = base64.b64decode(blob.json().get("content", "")).decode("utf-8", "ignore")
                if len(text.strip()) < 60:
                    continue
                import hashlib
                h = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
                if h in seen:               # already harvested this exact skill -> no dup vector
                    continue
                seen.add(h)
                name = re.sub(r"[^\w\- ]", "_", f"{repo}__{Path(f['path']).stem}")[:80]
                (_SKILLS / f"{name}.md").write_text(
                    f"---\ntitle: {Path(f['path']).stem}\nsource_repo: {owner}/{repo}\n"
                    f"tags: [skill, harvested]\n---\n\n> Harvested from "
                    f"https://github.com/{owner}/{repo}/blob/HEAD/{f['path']}\n\n"
                    f"{text}\n\n> [[06_Skills MOC]] · [[SASTRAVA OS MAP]]\n", encoding="utf-8")
                await ingest_text(text[:8000], title=f"skill:{Path(f['path']).stem}",
                                  role="shared", injected_by=actor, source="github_skill")
                added += 1
                await asyncio.sleep(0.3)
            except Exception:  # noqa: BLE001
                continue
    _save_seen(seen)
    await bus.emit("learn", actor, f"harvested {added} NEW skills from {owner}/{repo}")
    return added


async def harvest_once() -> dict:
    stats = {"repos": 0, "skills": 0}
    for spec in cfg.SKILL_REPOS:
        try:
            stats["skills"] += await harvest_repo(spec)
            stats["repos"] += 1
        except Exception as e:  # noqa: BLE001
            await bus.emit("error", "skill_harvester", f"{spec}: {e}")
    return stats


async def harvest_loop():
    await bus.emit("system", "skill_harvester",
                   f"skill harvester online ({len(cfg.SKILL_REPOS)} repos)")
    while True:
        try:
            s = await harvest_once()
            await bus.emit("memory", "skill_harvester",
                           f"cycle done: +{s['skills']} skills from {s['repos']} repos")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await bus.emit("error", "skill_harvester", f"cycle error: {e}")
        await asyncio.sleep(max(300, cfg.SKILL_HARVEST_INTERVAL_MIN * 60))
