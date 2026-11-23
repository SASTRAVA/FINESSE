from __future__ import annotations

import time
import base64
import json

import jwt
import pytest

from engine.db.storage import PlatformStorage
from engine.db.tenant_secrets import TenantSecretStore
from engine.security.jwks_manager import JWTKeyError, JWKSManager


@pytest.fixture
def manager(tmp_path):
    repository = PlatformStorage(str(tmp_path / "jwks.db"))
    secrets = TenantSecretStore(repository, "unit-test-master-key-material-000000000000")
    return JWKSManager(repository, secrets)


def claims(manager, *, now=None):
    issued = int(time.time() if now is None else now)
    return {"sub": "admin@example.test", "role": "CEO", "tier": 4,
            "tenant_id": "tenant-test", "amr": ["pwd", "mfa"],
            "iat": issued, "nbf": issued, "exp": issued + 3600,
            "jti": "test-session-id"}


def replace_header(token, updates):
    encoded = base64.urlsafe_b64encode(json.dumps(updates).encode()).decode().rstrip("=")
    _header, body, signature = token.split(".")
    return f"{encoded}.{body}.{signature}"


def test_jwks_rotation_keeps_old_signatures_valid_until_overlap_expiry(manager):
    first = manager.sign(claims(manager))
    first_kid = jwt.get_unverified_header(first)["kid"]
    assert manager.verify(first)["sub"] == "admin@example.test"
    assert [key["kid"] for key in manager.jwks()["keys"]] == [first_kid]

    second_key = manager.publish_rotation_key()
    assert second_key["kid"] in {key["kid"] for key in manager.jwks()["keys"]}
    manager.activate_rotation_key(second_key["kid"])
    second = manager.sign(claims(manager))
    assert manager.verify(first)["sub"] == manager.verify(second)["sub"]

    expired_at = manager.repository.get(
        "jwks_signing_keys", "default", first_kid)["valid_until"]
    assert first_kid in manager.retire_expired(now=expired_at + 1)
    with pytest.raises(JWTKeyError):
        manager.verify(first)
    assert manager.verify(second)["sub"] == "admin@example.test"


@pytest.mark.parametrize("header", [
    {"alg": "none", "kid": "valid"},
    {"alg": "HS256", "kid": "valid"},
])
def test_verifier_rejects_unsupported_or_untrusted_headers(manager, header):
    token = manager.sign(claims(manager))
    forged = replace_header(token, header)
    with pytest.raises(JWTKeyError):
        manager.verify(forged)


def test_verifier_requires_exact_kid_and_standard_claims(manager):
    token = manager.sign(claims(manager))
    header = jwt.get_unverified_header(token)
    header["kid"] = "unknown"
    forged = replace_header(token, header)
    with pytest.raises(JWTKeyError):
        manager.verify(forged)
