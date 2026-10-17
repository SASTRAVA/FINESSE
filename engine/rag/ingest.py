"""
Ingestion — THE HUMAN-TOUCH GATEWAY.

Every piece of knowledge enters the system here, put in by a person:
a pdf, a text file, a pasted requirement, a prompt. This is deliberately the
one place a human decides "the AI should know this." Nothing auto-scrapes itself
into the brain; a human always opens the gate.

Each ingested doc is chunked, embedded (quantized), stored in the shared vector
brain, AND mirrored to the Obsidian vault so you get live graph mapping of what
was fed in and by whom.
"""
from __future__ import annotations
import asyncio
import re
import time
from pathlib import Path
from typing import List

from ..config import cfg
from .store import store


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> List[str]:
    """Paragraph-aware chunking; keeps chunks near `size` chars with overlap."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}".strip()
        else:
            if buf:
                chunks.append(buf)
            if len(p) <= size:
                buf = p
            else:  # hard-split a huge paragraph
                for i in range(0, len(p), size - overlap):
                    chunks.append(p[i:i + size])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks or [text[:size]]


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader
    return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)


def _read_docx(path: Path) -> str:
    import docx
    return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)


def _read_xlsx(path: Path) -> str:
    """Read every sheet into clean, chunkable text (header row + pipe-delimited rows)."""
    import openpyxl
    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    out: list[str] = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            continue
        out.append(f"## Sheet: {ws.title}")
        cols = [("" if c is None else str(c)) for c in header]
        out.append(" | ".join(cols))
        out.append(" | ".join("---" for _ in cols))
        for r in rows:
            cells = [("" if c is None else str(c)) for c in r]
            if any(cells):
                out.append(" | ".join(cells))
    wb.close()
    return "\n".join(out) or "(empty workbook)"


def _read_csv(path: Path) -> str:
    import csv as _csv
    rows = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        for i, row in enumerate(_csv.reader(f)):
            rows.append(" | ".join(row))
            if i == 0:
                rows.append(" | ".join("---" for _ in row))
    return "\n".join(rows)


def _read_any(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _read_pdf(path)
    if ext == ".docx":
        return _read_docx(path)
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext == ".csv":
        return _read_csv(path)
    return path.read_text(encoding="utf-8", errors="ignore")


async def _store_chunks(chunks: List[str], meta: dict) -> dict:
    payloads = [{**meta, "chunk": i, "n_chunks": len(chunks)} for i in range(len(chunks))]
    ids = await store.upsert(chunks, payloads)
    return {"chunks": len(chunks), "ids": ids, **meta}


async def ingest_text(text: str, *, title: str, role: str, injected_by: str,
                      source: str = "prompt", lane: str | None = None,
                      sensitivity: str | None = None,
                      tenant_id: str = "default") -> dict:
    """Ingest raw text / a pasted requirement / a prompt (human-typed)."""
    from ..auth.rbac import SENSITIVITY_LEVELS, role_of
    document_lane = lane or role
    if document_lane not in ("coding", "prompt", "marketing", "bizdev", "exec",
                             "general", "security", "shared", "global"):
        document_lane = role_of(role).lane
    if sensitivity is None:
        sensitivity = ("confidential" if document_lane == "exec" or source == "vault"
                       else "internal")
    if sensitivity not in SENSITIVITY_LEVELS:
        raise ValueError(f"unsupported sensitivity: {sensitivity}")
    chunks = await asyncio.to_thread(chunk_text, text)     # CPU chunking off the loop (F4)
    meta = {"title": title, "role": document_lane, "lane": document_lane,
            "sensitivity": sensitivity, "injected_by": injected_by,
            "source": source, "tenant_id": tenant_id, "ts": time.time()}
    if source not in {"crawl", "skill_harvest", "vault"}:
        meta["owner"] = injected_by
    result = await _store_chunks(chunks, meta)
    await asyncio.to_thread(_mirror_to_vault, title, text, meta)   # sync file write off the loop
    return result


async def ingest_file(path: str | Path, *, role: str, injected_by: str,
                      lane: str | None = None, sensitivity: str | None = None,
                      tenant_id: str = "default") -> dict:
    """Ingest an uploaded pdf/docx/text/md file."""
    p = Path(path)
    text = await asyncio.to_thread(_read_any, p)   # sync pdf/docx/xlsx parse off the loop (F4)
    return await ingest_text(text, title=p.stem, role=role,
                             lane=lane, sensitivity=sensitivity,
                             injected_by=injected_by, source=p.suffix.lstrip(".") or "file",
                             tenant_id=tenant_id)


def _mirror_to_vault(title: str, text: str, meta: dict) -> None:
    """Write a note into 11_Knowledge_Base so Obsidian's graph shows the new input."""
    try:
        safe = re.sub(r"[^\w\- ]", "_", title)[:80] or "untitled"
        folder = (cfg.VAULT / "11_Knowledge_Base" / "_Injected"
                  if meta.get("tenant_id", "default") == "default"
                  else cfg.VAULT / "_Tenants" / re.sub(
                      r"[^\w\- ]", "_", str(meta["tenant_id"]))[:128]
                  / "11_Knowledge_Base" / "_Injected")
        folder.mkdir(parents=True, exist_ok=True)
        note = folder / f"{safe}.md"
        front = ("---\n"
                 f"title: {title}\n"
                 f"role: {meta.get('role')}\n"
                 f"lane: {meta.get('lane', meta.get('role'))}\n"
                 f"sensitivity: {meta.get('sensitivity', 'internal')}\n"
                 f"injected_by: {meta.get('injected_by')}\n"
                 f"source: {meta.get('source')}\n"
                 f"tags: [injected, {meta.get('role','general')}]\n"
                 "---\n\n")
        note.write_text(front + text, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[ingest] vault mirror failed: {e}")
