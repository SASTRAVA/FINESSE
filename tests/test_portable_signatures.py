import base64
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from engine.portable.signatures import (
    SignatureVerificationError,
    canonical_json,
    verify_license,
    verify_signed_bundle,
)
from engine.portable.license_gate import validate_portable_license


@pytest.fixture
def signer():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_text = base64.b64encode(public).decode("ascii")

    def sign(claims):
        signature = private.sign(canonical_json(claims))
        return {"claims": claims, "signature": base64.b64encode(signature).decode("ascii")}

    return public_text, sign


def test_offline_license_is_verified_and_expiry_is_enforced(signer):
    public_key, sign = signer
    claims = {"product": "FINESSE", "license_id": "lic-1", "tenant_id": "tenant-1",
              "features": ["offline"], "issued_at": 100, "not_before": 100,
              "expires_at": 500}
    assert verify_license(sign(claims), public_key, now=200) == claims

    with pytest.raises(SignatureVerificationError, match="currently valid"):
        verify_license(sign(claims), public_key, now=500)


def test_license_rejects_claim_tampering(signer):
    public_key, sign = signer
    claims = {"product": "FINESSE", "license_id": "lic-1", "tenant_id": "tenant-1",
              "features": [], "issued_at": 100, "expires_at": 500}
    document = sign(claims)
    document["claims"]["tenant_id"] = "other-tenant"
    with pytest.raises(SignatureVerificationError, match="signature"):
        verify_license(document, public_key, now=200)


def test_signed_update_bundle_is_hashed_before_acceptance(tmp_path, signer):
    public_key, sign = signer
    bundle = tmp_path / "update.tar"
    bundle.write_bytes(b"signed update bytes")
    content = bundle.read_bytes()
    claims = {"product": "FINESSE", "bundle_id": "update-1",
              "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
    assert verify_signed_bundle(bundle, sign(claims), public_key) == claims

    bundle.write_bytes(b"tampered update")
    with pytest.raises(SignatureVerificationError, match="content"):
        verify_signed_bundle(bundle, sign(claims), public_key)


def test_runtime_license_gate_is_optional_then_enforces_signature_tenant_and_expiry(
        tmp_path, signer):
    import json

    public_key, sign = signer
    claims = {"product": "FINESSE", "license_id": "lic-1", "tenant_id": "tenant-1",
              "features": ["offline"], "issued_at": 100, "not_before": 100,
              "expires_at": 500}
    license_file = tmp_path / "license.json"
    license_file.write_text(json.dumps(sign(claims)), encoding="utf-8")
    assert validate_portable_license(required=False, license_file="missing", public_key="",
                                     tenant_id="", now=200) is None
    assert validate_portable_license(required=True, license_file=license_file,
                                     public_key=public_key, tenant_id="tenant-1",
                                     now=200) == claims
    with pytest.raises(SignatureVerificationError, match="tenant"):
        validate_portable_license(required=True, license_file=license_file,
                                  public_key=public_key, tenant_id="other", now=200)
