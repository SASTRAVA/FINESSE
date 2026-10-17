from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine.config import cfg, _cors_origins, _storage_paths

ROOT = Path(__file__).resolve().parent.parent


class VercelDeploymentTests(unittest.TestCase):
    def test_vercel_asgi_entrypoint_routes_and_serves_ui(self):
        from fastapi.testclient import TestClient
        from api.index import app

        with TestClient(app, follow_redirects=True) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/workspace").status_code, 200)
            workspace = client.get("/workspace/")
            self.assertEqual(workspace.status_code, 200)
            script = re.search(r'src="([^"]+\.js)"', workspace.text)
            self.assertIsNotNone(script, "workspace HTML must reference a JS bundle")
            self.assertEqual(client.get(script.group(1)).status_code, 200)
            self.assertEqual(client.get("/dashboard").status_code, 200)
            self.assertEqual(client.get("/command").status_code, 200)
            self.assertEqual(client.get("/jarvis").status_code, 200)
            self.assertEqual(client.get("/voice").status_code, 200)
            self.assertEqual(client.get("/api/health").status_code, 200)
            self.assertEqual(client.get("/api/v1/services").status_code, 401)
            self.assertEqual(client.get("/api/sastrava/catalog").status_code, 401)
            with patch.object(cfg, "IS_VERCEL", True):
                self.assertEqual(
                    client.get("/api/index.py/api/health").status_code, 200)

    def test_vercel_defaults_and_domains_are_derived_without_touching_disk(self):
        data, vault = _storage_paths({"VERCEL": "1"})
        self.assertEqual(data, Path("/tmp/finesse-data").resolve())
        self.assertEqual(vault, Path("/tmp/finesse-vault").resolve())

        custom_data, custom_vault = _storage_paths({
            "VERCEL_ENV": "preview",
            "FINESSE_DATA_DIR": "custom-data",
            "VAULT_PATH": "custom-vault",
        })
        self.assertEqual(custom_data, (ROOT / "custom-data").resolve())
        self.assertEqual(custom_vault, (ROOT / "custom-vault").resolve())

        origins = _cors_origins({
            "CORS_ORIGINS": "https://console.example.test",
            "VERCEL_URL": "finesse-preview.vercel.app",
            "VERCEL_PROJECT_PRODUCTION_URL": "finesse.vercel.app",
        })
        self.assertEqual(origins, (
            "https://console.example.test",
            "https://finesse-preview.vercel.app",
            "https://finesse.vercel.app",
        ))

    def test_vercel_cold_start_bootstraps_ceo_and_public_catalog(self):
        with tempfile.TemporaryDirectory(prefix="finesse-vercel-") as temp_dir:
            env = os.environ.copy()
            env.update({
                "PYTHON_DOTENV_DISABLED": "1",
                "VERCEL": "1",
                "VERCEL_ENV": "preview",
                "VERCEL_URL": "finesse-test.vercel.app",
                "CEO_EMAIL": "vercel-test@example.test",
                "CEO_PASSWORD": "TestOnly-Vercel-Password-2026",
                "JWT_SECRET": "test-only-vercel-jwt-secret-" + "x" * 32,
                "KMS_MASTER_KEY": "test-only-vercel-kms-master-key-" + "y" * 32,
                "FINESSE_DATA_DIR": str(Path(temp_dir) / "data"),
                "VAULT_PATH": str(Path(temp_dir) / "vault"),
                "EMBEDDINGS_BACKEND": "hash",
                "QDRANT_PATH": str(Path(temp_dir) / "data" / "qdrant"),
            })
            script = """
import os
import json
from pathlib import Path
from fastapi.testclient import TestClient
from api.index import app
from engine.auth.users import users
from engine.config import cfg
from engine.db.storage import storage
from engine.rag.store import store

assert cfg.IS_VERCEL, "Vercel detection failed"
assert cfg.DATA_DIR.resolve() == Path(os.environ["FINESSE_DATA_DIR"]).resolve(), "data path override failed"
assert cfg.VAULT.resolve() == Path(os.environ["VAULT_PATH"]).resolve(), "vault path override failed"
assert "https://finesse-test.vercel.app" in cfg.CORS_ORIGINS, "dynamic CORS failed"
assert users.get(cfg.CEO_EMAIL) is not None, "CEO cold-start bootstrap failed"
with TestClient(app) as client:
    runtime = client.get("/api/v1/platform/runtime").json()
    login = client.post("/api/v1/auth/login", json={
        "email": cfg.CEO_EMAIL, "password": cfg.CEO_PASSWORD})
    assert login.status_code == 200, "CEO login failed"
    token = login.json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    services = client.get("/api/v1/services", headers=headers)
    catalog = client.get("/api/sastrava/catalog", headers=headers)
    assert services.status_code == 200, "service API dispatch failed"
    assert catalog.status_code == 200, "SASTRAVA catalog API dispatch failed"
    assert runtime["setup_ready"] is True, "configured runtime reported setup required"
    assert runtime["seeded_services_count"] == 6, "service seeds missing"
    assert runtime["seeded_playbooks_count"] == 6, "playbook seeds missing"
    assert runtime["catalog_repos_count"] >= 29, "repository seeds missing"
    assert len(storage.list("catalog_repositories", "default", limit=1000)) >= 29, "repository seed storage failed"
    assert store.backend_name() in {"qdrant", "memory"}, "vector backend unavailable"
    print(json.dumps(runtime))
"""
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=120, check=False)
            detail = next((line.strip() for line in reversed(result.stderr.splitlines())
                           if line.strip().startswith((
                               "AssertionError", "RuntimeError", "ValueError",
                               "ModuleNotFoundError", "ImportError"))),
                          "isolated Vercel bootstrap test failed")
            self.assertEqual(result.returncode, 0, detail)
            runtime = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(runtime["is_vercel"])

    def test_vercel_without_auth_secrets_returns_diagnostic_health_response(self):
        with tempfile.TemporaryDirectory(prefix="finesse-vercel-unconfigured-") as temp_dir:
            env = os.environ.copy()
            env.update({
                "PYTHON_DOTENV_DISABLED": "1",
                "VERCEL": "1",
                "FINESSE_DATA_DIR": str(Path(temp_dir) / "data"),
                "VAULT_PATH": str(Path(temp_dir) / "vault"),
                "EMBEDDINGS_BACKEND": "hash",
            })
            for name in ("CEO_EMAIL", "CEO_PASSWORD", "JWT_SECRET", "KMS_MASTER_KEY"):
                env.pop(name, None)
            script = """
from fastapi.testclient import TestClient
from api.index import app

with TestClient(app) as client:
    response = client.get("/api/health")
    assert response.status_code == 503, f"unexpected health status: {response.status_code}"
    payload = response.json()
    assert payload["ok"] is False, "health returned success without credentials"
    assert payload["is_vercel"] is True, "Vercel status flag missing"
    assert payload["vercel_setup_required"] is True, "setup diagnostic flag missing"
    assert {
        "CEO_EMAIL", "CEO_PASSWORD", "JWT_SECRET", "KMS_MASTER_KEY"
    }.issubset(payload["missing_env"]), (
        f"missing variable list was incomplete: {sorted(payload['missing_env'])}")
"""
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=ROOT, env=env,
                capture_output=True, text=True, timeout=120, check=False)
            detail = next((line.strip() for line in reversed(result.stderr.splitlines())
                           if line.strip().startswith((
                               "AssertionError", "RuntimeError", "ValueError",
                               "ModuleNotFoundError", "ImportError"))),
                          "unconfigured Vercel health diagnostic failed")
            self.assertEqual(
                result.returncode, 0, detail)

    def test_vercel_configuration_and_ignore_rules_cover_required_paths(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(config["buildCommand"],
                         "cd frontend && npm ci && npm run build")
        self.assertEqual(config["outputDirectory"], "engine/web/react-ui")
        destinations = {item["source"]: item["destination"]
                        for item in config["rewrites"]}
        for source in ("/api/:path*", "/hubapi/:path*", "/dashboard", "/command",
                       "/jarvis", "/voice", "/workspace/", "/workspace/:path*",
                       "/workspace", "/"):
            self.assertEqual(destinations[source], "/api/index.py")
        header_names = {
            header["key"]
            for rule in config["headers"]
            for header in rule["headers"]
        }
        self.assertTrue({
            "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"
        }.issubset(header_names))

        ignore = (ROOT / ".vercelignore").read_text(encoding="utf-8").splitlines()
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".vercel/", gitignore)
        for entry in (
            ".env", ".env.*", "!.env.example", ".venv/", "venv/", "data/",
            "vault/", "FINESSE VAULT/", "training/", "tests/",
            "frontend/node_modules/", ".git/", "__pycache__/", "*.pyc",
            "voice/friday.json", ".mcp.json", "HANDOFF.md", "ARCHITECTURE.md",
        ):
            self.assertIn(entry, ignore)

    def test_browser_api_requests_are_relative_and_same_origin(self):
        files = (
            ROOT / "frontend" / "src" / "workspace.tsx",
            ROOT / "engine" / "web" / "dashboard.html",
            ROOT / "engine" / "web" / "command.html",
            ROOT / "engine" / "web" / "jarvis.html",
        )
        absolute_local_fetch = re.compile(
            r"""fetch\s*\(\s*["'`]https?://(?:localhost|127\.0\.0\.1)""", re.I)
        for path in files:
            self.assertIsNone(
                absolute_local_fetch.search(path.read_text(encoding="utf-8")),
                f"{path.name} must use same-origin relative API URLs")


if __name__ == "__main__":
    unittest.main()
