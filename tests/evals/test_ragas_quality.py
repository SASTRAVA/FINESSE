"""Deterministic CI smoke checks for the golden dataset (no external judge calls)."""
import json
import re
from pathlib import Path

import pytest

DATASET = Path(__file__).with_name("golden_sastrava_dataset.json")


@pytest.mark.eval_smoke
def test_golden_dataset_coverage_and_security_contracts():
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    assert len(cases) >= 25
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(case["id"].startswith("consulting-") for case in cases) >= 20
    assert sum(case["id"].startswith("security-") for case in cases) >= 5
    for case in cases:
        assert case["question"] and case["context"] and case["answer"]
        known = set(case["expected_citations"])
        assert set(re.findall(r"\[C\d+\]", case["answer"])) <= known


@pytest.mark.eval_smoke
def test_citation_checker_rejects_unknown_ids():
    from engine.rag.citations import verify_and_attach_citations
    result = verify_and_attach_citations("Evidence [C1], hallucination [C99].", [])
    assert "[C1]" not in result["answer_markdown"]
    assert "[C99]" not in result["answer_markdown"]
