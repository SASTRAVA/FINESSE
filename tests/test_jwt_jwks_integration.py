from __future__ import annotations

import base64
import json

import jwt

from engine.auth import security as auth_security
from engine.db.storage import PlatformStorage
from engine.db.tenant_secrets import TenantSecretStore
from engine.security import jwks_manager as jwks_module
from engine.security.jwks_manager import JWKSManager


def test_configured_eddsa_tokens_use_kid_and_jwks_verification(tmp_path, monkeypatch):
    repository = PlatformStorage(str(tmp_path / "jwt.db"))
    secret_store = TenantSecretStore(repository, "unit-test-master-key-material-000000000000")
    manager = JWKSManager(repository, secret_store)
    monkeypatch.setattr(jwks_module, "jwks_manager", manager)
    monkeypatch.setattr(auth_security.cfg, "JWT_ALGORITHM", "EDDSA")

    token = auth_security.make_token("signed@example.test", "Analyst", 1, "signed-tenant")
    assert auth_security.decode_token(token)["sub"] == "signed@example.test"
    assert jwt.get_unverified_header(token)["kid"]
    assert auth_security.decode_token(token.replace(".", "x", 1)) is None

    altered = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "===").decode())
    altered["kid"] = "unknown-key"
    encoded = base64.urlsafe_b64encode(json.dumps(altered).encode()).decode().rstrip("=")
    _header, body, signature = token.split(".")
    assert auth_security.decode_token(f"{encoded}.{body}.{signature}") is None
