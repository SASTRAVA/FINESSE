"""Validate an explicit JSON catalog candidate file against the 8-gate policy."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from engine.knowledge.universal_catalog import certify_candidate

_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


def validate_candidates(records: list[dict]) -> list[dict]:
    results = []
    for record in records:
        name = str(record.get("full_name", ""))
        if not _REPO.fullmatch(name):
            raise ValueError("each candidate must use owner/repository syntax")
        results.append({"full_name": name, **certify_candidate(record.get("evidence", {}))})
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    if args.input.suffix.lower() != ".json":
        parser.error("candidate validation accepts an explicit JSON file")
    if not args.input.is_file():
        parser.error("input file does not exist")
    records = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        parser.error("input JSON must be a list")
    print(json.dumps(validate_candidates(records), indent=2))


if __name__ == "__main__":
    main()
