from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PortableDeploymentTests(unittest.TestCase):
    def test_portable_compose_keeps_runtime_local_and_data_on_drive(self):
        compose = (ROOT / "deploy" / "compose.portable.yaml").read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1:${FINESSE_PORT:-8600}:8600"', compose)
        self.assertIn("internal: true", compose)
        self.assertIn("../portable-runtime/data:/app/data", compose)
        self.assertIn("../portable-runtime/vault:/app/vault", compose)
        self.assertIn("../portable-runtime/ollama:/root/.ollama", compose)
        self.assertIn("LOCAL_LLM_BASE_URL: http://ollama:11434/v1", compose)
        self.assertIn("EMBEDDINGS_BACKEND: hash", compose)
        self.assertIn('SALES_DRY_RUN: "true"', compose)
        self.assertIn('EMAIL_LIVE_ENABLED: "false"', compose)
        self.assertIn('VOICE_LIVE_ENABLED: "false"', compose)
        self.assertNotIn("11434:", compose)
        self.assertNotIn("postgresql://", compose)

    def test_model_provisioning_overlay_is_explicit_and_data_is_ignored(self):
        overlay = (ROOT / "deploy" / "compose.portable.provision.yaml").read_text(
            encoding="utf-8")
        self.assertIn("internal: false", overlay)
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/portable-runtime/", ignore)
        self.assertIn("!.env.portable.example", ignore)

    def test_portable_environment_template_has_no_usable_secret_defaults(self):
        template = (ROOT / ".env.portable.example").read_text(encoding="utf-8")
        for name in ("JWT_SECRET", "KMS_MASTER_KEY", "CEO_EMAIL", "CEO_PASSWORD"):
            self.assertIn(f"{name}=\n", template)


if __name__ == "__main__":
    unittest.main()
