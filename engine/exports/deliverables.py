"""SASTRAVA-branded DOCX export with escaped source content and classification marks."""
from __future__ import annotations

from io import BytesIO
import re

from docx import Document

from ..rag.citations import verify_and_attach_citations

_SENSITIVITY = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_CITATION_ID = re.compile(r"C[0-9]{1,8}\Z")


def resolve_verified_citations(citations: list[dict], *, tenant_id: str,
                               principal_id: str, allowed_lanes: tuple[str, ...],
                               max_sensitivity: str, get_document) -> list[dict]:
    """Replace client citation claims with active tenant document metadata."""
    maximum = _SENSITIVITY.get(max_sensitivity, -1)
    verified = []
    seen_ids: set[str] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        cite_id = str(item.get("cite_id", item.get("id", "")))
        doc_id = item.get("doc_id", item.get("document_id"))
        version = item.get("version")
        if (not _CITATION_ID.fullmatch(cite_id) or not isinstance(doc_id, str)
                or cite_id in seen_ids or not doc_id
                or not isinstance(version, int) or isinstance(version, bool)):
            continue
        record = get_document(tenant_id, doc_id)
        if (not record or record.get("status") != "ACTIVE"
                or record.get("current_version") != version
                or record.get("lane") not in allowed_lanes
                or _SENSITIVITY.get(record.get("sensitivity"), 3) > maximum
                or record.get("sensitivity") == "restricted"):
            continue
        acl = record.get("acl_principal_ids", [])
        if acl and principal_id not in acl:
            continue
        # Titles/source labels come only from the tenant-scoped server record.
        verified.append({"cite_id": cite_id, "doc_id": doc_id, "version": version,
                         "title": str(record.get("title", "Source"))[:300],
                         "source_type": str(record.get("source_type", "DOCUMENT"))[:80]})
        seen_ids.add(cite_id)
    return verified


def build_docx(*, title: str, summary: str, listen: str, shape: str, deliver: str,
               sensitivity: str, citations: list[dict], tenant_name: str = "SASTRAVA") -> bytes:
    if sensitivity not in {"public", "internal", "confidential"}:
        raise ValueError("restricted content cannot be exported")
    verified = verify_and_attach_citations("\n".join((summary, listen, shape, deliver)), citations)
    doc = Document()
    section = doc.sections[0]
    section.header.paragraphs[0].text = f"{sensitivity.upper()} · {tenant_name}"
    section.footer.paragraphs[0].text = "Prepared with FINESSE · Verify before external distribution"
    doc.add_heading(tenant_name, 0)
    doc.add_heading(title, 1)
    doc.add_heading("Executive Summary", 2)
    doc.add_paragraph(summary)
    for heading, body in (("Listen", listen), ("Shape", shape), ("Deliver", deliver)):
        doc.add_heading(heading, 2)
        doc.add_paragraph(body)
    doc.add_heading("Verified Sources", 2)
    for citation in verified["citations"]:
        cite_id = citation.get("citation_id", citation.get("cite_id", citation.get("id", "")))
        doc.add_paragraph(f"[{cite_id}] {citation.get('title', 'Source')} — "
                          f"{citation.get('source_type', 'UNKNOWN')} · "
                          f"{citation.get('page_or_section', '')}", style="List Bullet")
    if verified["unverified_citation_warnings"]:
        doc.add_paragraph("Unverified source references were removed. Review source coverage.")
    output = BytesIO()
    doc.save(output)
    return output.getvalue()
