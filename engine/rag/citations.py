"""Stable, typed retrieval provenance and post-generation citation validation."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_CITATION_TOKEN = re.compile(r"\[(C\d+)\]")


@dataclass(frozen=True)
class CitationRecord:
    cite_id: str
    doc_id: str | None
    version: int | None
    title: str
    source_type: str
    page_or_section: str | None
    char_start: int | None
    char_end: int | None
    snippet_preview: str
    lane: str
    sensitivity: str
    external_url_or_vault_path: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def citation_record(cite_id: str, payload: dict, snippet: str) -> CitationRecord:
    version = payload.get("version")
    return CitationRecord(
        cite_id=cite_id, doc_id=payload.get("doc_id") or payload.get("document_id"),
        version=version if isinstance(version, int) else None,
        title=str(payload.get("title", "?")),
        source_type=str(payload.get("source_type", payload.get("source", "?"))),
        page_or_section=payload.get("page_or_section"),
        char_start=payload.get("char_start") if isinstance(payload.get("char_start"), int) else None,
        char_end=payload.get("char_end") if isinstance(payload.get("char_end"), int) else None,
        snippet_preview=snippet[:280], lane=str(payload.get("lane", "general")),
        sensitivity=str(payload.get("sensitivity", "internal")),
        external_url_or_vault_path=(payload.get("external_url") or payload.get("vault_path")),
    )


def verify_and_attach_citations(answer_markdown: str, citations: list[dict]) -> dict:
    """Drop invalid [C#] markers and return only cited provenance records."""
    by_id = {str(record.get("cite_id", record.get("id", ""))): record
             for record in citations}
    used: list[dict] = []
    warnings: list[str] = []

    def replace(match):
        cite_id = match.group(1)
        if cite_id not in by_id:
            warnings.append(f"Unknown citation reference [{cite_id}] was removed.")
            return ""
        record = by_id[cite_id]
        if record not in used:
            used.append(record)
        return match.group(0)

    validated = _CITATION_TOKEN.sub(replace, answer_markdown)
    return {"answer_markdown": validated, "citations": used,
            "unverified_citation_warnings": warnings}
