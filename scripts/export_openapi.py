"""Export a reviewed route-to-authentication inventory from the live FastAPI schema."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "docs" / "security" / "route_auth_inventory.json"

PUBLIC_REASONS = {
    ("POST", "/api/login"): "Credential exchange; login throttling and password verification apply.",
    ("GET", "/api/roles"): "Non-sensitive role names support the sign-in client.",
    ("GET", "/"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/universe"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/dashboard"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/innovation"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/voice"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/jarvis"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/command"): "Static sign-in page; application data APIs enforce authentication.",
    ("GET", "/health"): "Liveness probe returns only a generic online status.",
    ("GET", "/api/health"): "Setup diagnostic returns only missing setting names, never values.",
    ("GET", "/api/v1/platform/runtime"): "Public deployment readiness booleans and counts only.",
    ("POST", "/hubapi/token"): "Credential exchange; login throttling and password verification apply.",
    ("GET", "/hubapi/swarm/clusters"): "Public static agent catalog; contains no tenant data.",
    ("POST", "/api/v1/auth/login"): "Credential exchange; login throttling and password verification apply.",
    ("POST", "/api/v1/email/unsubscribe/{token}"): "Signed, purpose-bound, expiring unsubscribe capability token.",
    ("GET", "/api/v1/email/unsubscribe/{token}"): "Signed, purpose-bound, expiring unsubscribe capability token.",
    ("POST", "/api/v1/webhooks/providers/email"): "Provider HMAC signature is verified before tenant-scoped processing.",
    ("POST", "/api/v1/webhooks/providers/voice"): "Provider HMAC or Twilio request signature is verified before processing.",
    ("POST", "/api/v1/webhooks/providers/voice/opt-out"): "Twilio request signature is verified before tenant-scoped opt-out.",
}


def build_inventory() -> dict:
    os.environ.setdefault("JWT_SECRET", "route-matrix-test-only-" + "x" * 40)
    os.environ.setdefault("CEO_EMAIL", "route-matrix@example.invalid")
    os.environ.setdefault("CEO_PASSWORD", "Route-matrix-only-2026")
    os.environ.setdefault("KMS_MASTER_KEY", "route-matrix-kms-only-" + "k" * 40)
    from engine.main import app

    operations = []
    for path, methods in app.openapi()["paths"].items():
        for method, operation in methods.items():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            verb = method.upper()
            secured = bool(operation.get("security"))
            reason = PUBLIC_REASONS.get((verb, path)) if not secured else None
            operations.append({
                "method": verb,
                "path": path,
                "operation_id": operation["operationId"],
                "authenticated": secured,
                "security": operation.get("security", []),
                "public_reason": reason,
            })
    operations.sort(key=lambda item: (item["path"], item["method"], item["operation_id"]))

    websockets = [
        {"path": "/ws", "authentication": "opaque single-use ticket", "origin_check": True},
        {"path": "/hubapi/gatekeeper/stream", "authentication": "opaque single-use ticket",
         "origin_check": True},
    ]
    return {"schema_version": 1, "openapi_version": app.openapi()["openapi"],
            "http_operations": operations, "websockets": websockets}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="fail if the checked-in inventory differs from live OpenAPI")
    args = parser.parse_args()
    current = json.dumps(build_inventory(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != current:
            raise SystemExit("route-auth inventory is stale; run python scripts/export_openapi.py")
        print(f"route-auth inventory verified: {OUTPUT.relative_to(ROOT)}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(current, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(json.loads(current)['http_operations'])} HTTP operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
