"""Import explicitly supplied catalog files; never searches local directories."""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

from engine.knowledge.universal_catalog import certify_candidate

_REPO = re.compile(r"(?:https?://github\.com/)?([A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})")
_PROTECTED = {".env", ".mcp.json", "friday.json", "handoff.md", "architecture.md",
              "data", "vault", "finesse vault"}


def _safe_path(path: Path) -> None:
    parts = {part.casefold() for part in path.parts}
    if parts & _PROTECTED or "training/data" in str(path).casefold().replace("\\", "/"):
        raise ValueError("catalog importer refuses protected paths")


def _records_from_text(text: str) -> list[dict]:
    names = sorted(set(match.group(1).rstrip(".,)") for match in _REPO.finditer(text)))
    return [{"full_name": name, "status": "DISCOVERED",
             "certification_stage": "SOURCE_INVENTORY_ONLY",
             "certification": certify_candidate({})} for name in names]


def import_catalog(source: Path) -> list[dict]:
    _safe_path(source)
    suffix = source.suffix.casefold()
    if suffix == ".json":
        value = json.loads(source.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value = value.get("repositories", [])
        if not isinstance(value, list):
            raise ValueError("JSON catalog must contain a list of repositories")
        text = "\n".join(
            str(row.get("full_name", row.get("repository", row.get("url", ""))))
            for row in value if isinstance(row, dict))
    elif suffix in {".tsv", ".txt"}:
        with source.open(encoding="utf-8", newline="") as handle:
            rows = csv.DictReader(handle, delimiter="\t")
            text = "\n".join(str(row.get("full_name", row.get("repository", row.get("url", ""))))
                             for row in rows)
    elif suffix == ".pdf":
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(source)).pages)
    else:
        raise ValueError("supported catalog formats are PDF, JSON, and TSV")
    return _records_from_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    _safe_path(args.source)
    if args.output:
        _safe_path(args.output)
    result = import_catalog(args.source)
    encoded = json.dumps({"records": result, "count": len(result)}, indent=2)
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
