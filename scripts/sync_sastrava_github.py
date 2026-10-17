"""Build a sanitized catalog of public SASTRAVA GitHub projects (excluding FINESSE)."""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.knowledge.sanitize import sanitize_public_text

OUTPUT = ROOT / "engine" / "knowledge" / "github_portfolio.json"
API = "https://api.github.com"
ORG = "SASTRAVA"


def _public_repo(repo: dict) -> dict | None:
    name = repo.get("name")
    owner = repo.get("owner")
    if (repo.get("private") is not False or not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name)
            or name.casefold() == "finesse"
            or not isinstance(owner, dict)
            or str(owner.get("login") or "").casefold() != ORG.casefold()):
        return None
    return {
        "name": name,
        "url": f"https://github.com/{ORG}/{name}",
        "description": sanitize_public_text(str(repo.get("description") or "")),
        "language": sanitize_public_text(str(repo.get("language") or "")),
        "private": False,
        "summary": "",
    }


async def fetch_public_projects(client: httpx.AsyncClient | None = None) -> list[dict]:
    owned_client = client is None
    client = client or httpx.AsyncClient(
        timeout=20, follow_redirects=True,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "FINESSE-SASTRAVA-public-catalog/1.0"},
    )
    try:
        response = await client.get(f"{API}/orgs/{ORG}/repos",
                                    params={"type": "public", "per_page": 100})
        if response.status_code == 404:
            response = await client.get(f"{API}/users/{ORG}/repos",
                                        params={"type": "public", "per_page": 100})
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            raise RuntimeError("GitHub public repository response was not a list")
        repositories = [_public_repo(item) for item in items if isinstance(item, dict)]
        public = [item for item in repositories if item]
        for repo in public:
            readme = await client.get(
                f"{API}/repos/{ORG}/{repo['name']}/readme")
            if readme.status_code == 404:
                continue
            readme.raise_for_status()
            data = readme.json()
            if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
                raise RuntimeError(f"GitHub README payload was invalid for {repo['name']}")
            raw = base64.b64decode(data["content"], validate=False).decode(
                "utf-8", errors="replace")
            repo["summary"] = sanitize_public_text(raw)[:5000]
        return public
    finally:
        if owned_client:
            await client.aclose()


async def _index() -> int:
    from engine.knowledge.indexing import index_public_catalog
    from engine.rag.store import store
    return await index_public_catalog(store)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-index", action="store_true",
                        help="write the sanitized source catalog without updating vectors")
    args = parser.parse_args(argv)
    repos = asyncio.run(fetch_public_projects())
    OUTPUT.write_text(json.dumps(
        {"version": 1, "organization": ORG, "repositories": repos},
        ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    indexed = 0 if args.no_index else asyncio.run(_index())
    print(f"[sastrava-github] saved {len(repos)} public projects; indexed {indexed} chunks")
    return len(repos)


if __name__ == "__main__":
    main()
