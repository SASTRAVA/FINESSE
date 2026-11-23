"""Fail-closed evidence verifier for production gates and upscaling pillars.

Evidence manifest entries are reviewer assertions backed by checked-in files;
this tool does not replace service tests, legal review, or independent audit.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GATES = {f"G{i}": title for i, title in enumerate((
        "Repository license, history secret scan, and owner lockdown evidence",
        "Green CI across tests, lint, migrations, and frontend build",
        "Complete route-auth matrix for HTTP and WebSocket operations",
        "Live PostgreSQL RLS/pool and Qdrant tenant-isolation acceptance",
        "RAG taint propagation, cloud-egress blocking, and scrubber acceptance",
        "Gatekeeper exact-action binding and single-use approval acceptance",
        "Production Redis sessions, user state, and PostgreSQL audit acceptance",
        "Durable asynchronous ingestion, bounds, DLQ, and vault adapter acceptance",
        "Gated delivery and database/vector/portable recovery drills",
        "30+ VU multi-replica load, chaos, and independent red-team acceptance",
        "Production logging, telemetry, metrics, health, and graceful-drain acceptance",
        "Compliance controls, distributed switches, rollback, and owner sign-off",
    ), 1)}
PILLARS = {f"U{i}": title for i, title in enumerate((
        "Multi-tenant identity lifecycle and SSO acceptance",
        "Approved source mapping for the second upscaling pillar",
        "Mandatory Qdrant multitenancy and hybrid retrieval acceptance",
        "Durable append-only audit and secret-free observability acceptance",
        "Human approval and sandboxed plugin acceptance",
        "Tenant administration and portable-runtime acceptance",
        "Approved source mapping for the seventh upscaling pillar",
        "Compliance, supply chain, red-team, and launch-readiness acceptance",
    ), 1)}


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def evaluate(evidence_path: Path) -> dict:
    try:
        manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        manifest = {}
    entries = manifest.get("evidence", {}) if isinstance(manifest, dict) else {}
    results = []
    for group, definitions in (("gate", GATES), ("pillar", PILLARS)):
        for identifier, title in definitions.items():
            entry = entries.get(identifier, {}) if isinstance(entries, dict) else {}
            if not isinstance(entry, dict):
                entry = {}
            paths = entry.get("evidence", [])
            reasons = []
            verified_files = []
            if entry.get("status") != "PASS":
                reasons.append("no reviewer-approved PASS evidence")
            if not isinstance(paths, list) or not paths:
                reasons.append("evidence file list is empty")
                paths = []
            for raw_path in paths:
                if not isinstance(raw_path, str) or not raw_path.strip():
                    reasons.append("evidence path is invalid")
                    continue
                path = (ROOT / raw_path).resolve()
                if not path.is_relative_to(ROOT) or not path.is_file():
                    reasons.append(f"evidence file is missing or outside repository: {raw_path}")
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                verified_files.append({"path": path.relative_to(ROOT).as_posix(),
                                       "sha256": digest})
            status = "PASS" if not reasons and verified_files else "FAIL"
            results.append({"id": identifier, "group": group, "title": title,
                            "status": status, "evidence_files": verified_files,
                            "reasons": reasons})
    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "evidence_manifest": (evidence_path.resolve().as_posix()
                                  if evidence_path.is_file() else None),
            "results": results,
            "passed": sum(item["status"] == "PASS" for item in results),
            "failed": sum(item["status"] == "FAIL" for item in results),
            "signature": None,
            "signature_status": "UNSIGNED_NO_SIGNING_KEY"}


def _sign_if_configured(report: dict) -> None:
    pem = os.environ.get("FINESSE_SIGNOFF_PRIVATE_KEY", "")
    if not pem:
        return
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(pem.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("FINESSE_SIGNOFF_PRIVATE_KEY must be an Ed25519 PEM key")
    payload = {name: value for name, value in report.items()
               if name not in {"signature", "signature_status"}}
    report["signature"] = base64.b64encode(key.sign(_canonical(payload))).decode("ascii")
    report["signature_status"] = "SIGNED_ED25519"


def _markdown(report: dict) -> str:
    lines = ["# Production readiness evidence report", "",
             f"Generated: {report['generated_at']}",
             f"Passed: {report['passed']}/20 | Failed: {report['failed']}/20",
             f"Signature: {report['signature_status']}", "",
             "This is not a compliance certificate. PASS entries are reviewer-asserted evidence whose files are hashed below.",
             "", "| ID | Status | Requirement | Evidence / reason |",
             "| --- | --- | --- | --- |"]
    for item in report["results"]:
        details = [f"`{entry['path']}` ({entry['sha256'][:12]})"
                   for entry in item["evidence_files"]]
        details.extend(item["reasons"])
        lines.append(f"| {item['id']} | {item['status']} | {item['title']} | {'; '.join(details)} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path,
                        default=ROOT / "docs" / "readiness" / "production_evidence.json")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="require every gate and pillar plus a signature (production use)")
    args = parser.parse_args()
    report = evaluate(args.evidence)
    try:
        _sign_if_configured(report)
    except (ValueError, TypeError) as exc:
        report["signature_status"] = f"SIGNING_ERROR: {exc}"
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded, encoding="utf-8")
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(_markdown(report), encoding="utf-8")
    print(f"Production gates: {report['passed']}/20 passed; "
          f"{report['failed']}/20 failed; {report['signature_status']}")
    strict_ok = report["failed"] == 0 and report["signature_status"] == "SIGNED_ED25519"
    if args.strict and not strict_ok:
        return 1
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
