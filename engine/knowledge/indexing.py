from __future__ import annotations

import uuid

from .sastrava import catalog_response


async def index_public_catalog(vector_store) -> int:
    """Index sanitized public catalogs without traversing or mirroring the private vault."""
    from ..rag.ingest import chunk_text

    catalog = catalog_response()
    documents: list[tuple[str, str, str]] = []
    for service in catalog["services"]:
        documents.append((
            f"SASTRAVA service: {service['name']}",
            f"{service['name']}\nPillar: {service['pillar']}\n{service['description']}",
            "sastrava_public",
        ))
    for playbook in catalog["playbooks"]:
        if playbook["content"].strip():
            documents.append((playbook["name"], playbook["content"], "sastrava_playbook"))
    for page in catalog["site_pages"]:
        if page["content"].strip():
            documents.append((page["title"] or page["url"], page["content"], "sastrava_site"))
    for repo in catalog["public_repositories"]:
        summary = "\n".join(part for part in (repo["description"], repo["summary"]) if part)
        if summary:
            documents.append((repo["name"], summary, "sastrava_github"))

    texts, payloads, ids = [], [], []
    for title, content, source in documents:
        for index, chunk in enumerate(chunk_text(content)):
            texts.append(chunk)
            payloads.append({
                "title": title, "lane": "general", "role": "general",
                "sensitivity": "public", "source": source, "chunk": index,
            })
            ids.append(str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"finesse-public-catalog:{source}:{title}:{index}:{chunk}")))
    if not texts:
        return 0
    await vector_store.upsert(texts, payloads, ids=ids)
    return len(texts)
