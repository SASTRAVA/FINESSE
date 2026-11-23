import json

from scripts import verify_production_gates as gates


def test_unavailable_evidence_fails_closed_for_all_20_requirements(tmp_path):
    report = gates.evaluate(tmp_path / "missing-evidence.json")
    assert report["passed"] == 0
    assert report["failed"] == 20
    assert len(report["results"]) == 20
    assert all(item["status"] == "FAIL" for item in report["results"])


def test_evidence_paths_must_exist_inside_the_repository(tmp_path):
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"evidence": {
        "G1": {"status": "PASS", "evidence": [str(tmp_path / "proof.txt")]}}}),
        encoding="utf-8")
    report = gates.evaluate(evidence)
    g1 = next(item for item in report["results"] if item["id"] == "G1")
    assert g1["status"] == "FAIL"
    assert "outside repository" in g1["reasons"][-1]


def test_strict_cli_emits_report_and_fails_when_signoff_is_unavailable(
        tmp_path, monkeypatch, capsys):
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    monkeypatch.setattr(gates.sys, "argv", [
        "verify_production_gates", "--strict", "--evidence",
        str(tmp_path / "missing.json"), "--json-out", str(report_json),
        "--markdown-out", str(report_md)])
    assert gates.main() == 1
    assert "0/20 passed" in capsys.readouterr().out
    assert json.loads(report_json.read_text(encoding="utf-8"))["failed"] == 20
    assert "UNSIGNED_NO_SIGNING_KEY" in report_md.read_text(encoding="utf-8")
