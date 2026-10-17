"""Fetch and sanitize SASTRAVA's public website content into a tracked catalog."""
from __future__ import annotations

import argparse
import asyncio
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import sys
from urllib.parse import urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.knowledge.sanitize import sanitize_public_text

OUTPUT = ROOT / "engine" / "knowledge" / "site_pages.json"
SITE_ORIGIN = "https://sastrava.com"
ALLOWED_HOSTS = {"sastrava.com", "www.sastrava.com"}
FALLBACK_PATHS = (
    "/", "/services-hub/", "/services-hub/learn", "/portfolio/",
    "/about/", "/contact/", "/cybersecurity/", "/blog/",
)


class _PageText(HTMLParser):
    _SKIP = {"script", "style", "svg", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title = False
        self.title_parts: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, _attrs):
        if tag in self._SKIP:
            self.skip_depth += 1
        elif tag == "title":
            self.title = True
        elif tag in {"h1", "h2", "h3", "p", "li"} and not self.skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "title":
            self.title = False
        elif tag in {"h1", "h2", "h3", "p", "li"} and not self.skip_depth:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self.title:
            self.title_parts.append(text)
        self.parts.append(text)


def _safe_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or host not in ALLOWED_HOSTS
            or port not in (None, 443) or parsed.username or parsed.password):
        return None
    return urlunparse(("https", parsed.netloc, parsed.path or "/", "", "", ""))


def _extract_page(url: str, html: str) -> dict:
    parser = _PageText()
    parser.feed(html)
    content = sanitize_public_text(" ".join(parser.parts))
    return {
        "url": url,
        "title": sanitize_public_text(" ".join(parser.title_parts))[:200],
        "content": content[:10000],
    }


async def _get_allowed(client: httpx.AsyncClient, url: str):
    current = _safe_url(url)
    for _ in range(5):
        if not current:
            return None
        response = await client.get(current)
        if response.is_redirect:
            location = response.headers.get("location")
            current = _safe_url(urljoin(current, location)) if location else None
            continue
        if not _safe_url(str(response.url)):
            return None
        return response
    return None


async def _collect_urls(client: httpx.AsyncClient) -> list[str]:
    urls = {SITE_ORIGIN + path for path in FALLBACK_PATHS}
    try:
        response = await _get_allowed(client, SITE_ORIGIN + "/sitemap.xml")
        if response is None:
            return sorted(urls)
    except httpx.HTTPError:
        logging.getLogger("finesse.knowledge").warning(
            "SASTRAVA sitemap unavailable; using vetted fallback URLs")
        return sorted(urls)
    if response.is_success:
        try:
            root = ET.fromstring(response.text)
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] == "loc" and element.text:
                    safe = _safe_url(element.text.strip())
                    if safe:
                        urls.add(safe)
        except ET.ParseError:
            logging.getLogger("finesse.knowledge").warning(
                "SASTRAVA sitemap was invalid; using vetted fallback URLs")
    return sorted(urls)


async def fetch_site_pages(client: httpx.AsyncClient | None = None) -> list[dict]:
    owned_client = client is None
    client = client or httpx.AsyncClient(
        timeout=20, follow_redirects=False,
        headers={"User-Agent": "FINESSE-SASTRAVA-public-catalog/1.0"},
    )
    try:
        urls = await _collect_urls(client)
        semaphore = asyncio.Semaphore(6)
        failures = 0

        async def fetch(url: str):
            nonlocal failures
            safe = _safe_url(url)
            if not safe:
                failures += 1
                return None
            async with semaphore:
                try:
                    response = await _get_allowed(client, safe)
                    if response is None:
                        failures += 1
                        return None
                    final_url = _safe_url(str(response.url))
                    if not response.is_success or not final_url:
                        failures += 1
                        return None
                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type:
                        failures += 1
                        return None
                    return _extract_page(final_url, response.text)
                except httpx.HTTPError:
                    failures += 1
                    return None

        results = await asyncio.gather(*(fetch(url) for url in urls))
        if failures:
            logging.getLogger("finesse.knowledge").warning(
                "Skipped %d SASTRAVA pages after safe fetch checks", failures)
        unique = {page["url"]: page for page in results if page and page["content"]}
        return [unique[url] for url in sorted(unique)]
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
    pages = asyncio.run(fetch_site_pages())
    if not pages:
        raise RuntimeError("No allowed SASTRAVA website pages could be fetched.")
    OUTPUT.write_text(json.dumps(
        {"version": 1, "site": SITE_ORIGIN, "pages": pages},
        ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    indexed = 0 if args.no_index else asyncio.run(_index())
    print(f"[sastrava-site] saved {len(pages)} sanitized pages; indexed {indexed} chunks")
    return len(pages)


if __name__ == "__main__":
    main()
