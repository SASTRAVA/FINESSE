"""Ed25519 verification for offline FINESSE licenses and update bundles."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class SignatureVerificationError(ValueError):
    """A signed artifact is malformed, untrusted, expired, or has changed."""


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def load_ed25519_public_key(value: bytes | str) -> Ed25519PublicKey:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    try:
        key = serialization.load_pem_public_key(encoded)
    except ValueError:
        try:
            raw = base64.b64decode(encoded, validate=True)
            key = Ed25519PublicKey.from_public_bytes(raw)
        except (ValueError, TypeError) as exc:
            raise SignatureVerificationError("Ed25519 public key is invalid") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise SignatureVerificationError("an Ed25519 public key is required")
    return key


def _verify_signature(public_key: Ed25519PublicKey, message: bytes, signature: str) -> None:
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
        public_key.verify(signature_bytes, message)
    except (ValueError, InvalidSignature) as exc:
        raise SignatureVerificationError("signature verification failed") from exc


def verify_license(document: dict, public_key: bytes | str, *, now: int | None = None) -> dict:
    """Verify license signature, product, validity window, and required identity fields."""
    if not isinstance(document, dict) or not isinstance(document.get("claims"), dict):
        raise SignatureVerificationError("license claims are missing")
    claims = document["claims"]
    if (claims.get("product") != "FINESSE"
            or not isinstance(claims.get("license_id"), str)
            or not claims["license_id"].strip()):
        raise SignatureVerificationError("license product or ID is invalid")
    if (not isinstance(claims.get("tenant_id"), str)
            or not claims["tenant_id"].strip()
            or not isinstance(claims.get("features"), list)
            or any(not isinstance(feature, str) or not feature.strip()
                   for feature in claims["features"])):
        raise SignatureVerificationError("license tenant or features are invalid")
    issued_at = claims.get("issued_at")
    not_before = claims.get("not_before", issued_at)
    expires_at = claims.get("expires_at")
    if not all(isinstance(value, int) and not isinstance(value, bool)
               for value in (issued_at, not_before, expires_at)):
        raise SignatureVerificationError("license timestamps are invalid")
    current = int(time.time() if now is None else now)
    if issued_at > current or not_before > current or expires_at <= current or expires_at <= issued_at:
        raise SignatureVerificationError("license is not currently valid")
    _verify_signature(load_ed25519_public_key(public_key), canonical_json(claims),
                      str(document.get("signature", "")))
    return dict(claims)


def verify_signed_bundle(bundle_path: str | Path, manifest: dict,
                         public_key: bytes | str) -> dict:
    """Hash an update bundle and verify its detached signed metadata without extracting it."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("claims"), dict):
        raise SignatureVerificationError("bundle manifest claims are missing")
    claims = manifest["claims"]
    if (claims.get("product") != "FINESSE"
            or not isinstance(claims.get("bundle_id"), str)
            or not claims["bundle_id"].strip()):
        raise SignatureVerificationError("bundle product or ID is invalid")
    expected_hash = claims.get("sha256")
    expected_size = claims.get("size_bytes")
    if (not isinstance(expected_hash, str) or len(expected_hash) != 64
            or any(char not in "0123456789abcdef" for char in expected_hash)
            or not isinstance(expected_size, int) or isinstance(expected_size, bool)
            or expected_size < 0):
        raise SignatureVerificationError("bundle digest or size is invalid")
    path = Path(bundle_path)
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    if expected_hash != digest.hexdigest() or expected_size != size:
        raise SignatureVerificationError("bundle content does not match its signed manifest")
    _verify_signature(load_ed25519_public_key(public_key), canonical_json(claims),
                      str(manifest.get("signature", "")))
    return dict(claims)
