"""Tenant-bound envelope encryption for provider credentials at rest."""
from __future__ import annotations

import base64
import binascii
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import cfg
from .storage import PlatformStorage, storage


class TenantSecretStore:
    def __init__(self, repository: PlatformStorage = storage, master_key: str | None = None,
                 *, active_key_id: str | None = None,
                 keyring: dict[str, str] | None = None):
        self.repository = repository
        self._master_key = master_key if master_key is not None else cfg.KMS_MASTER_KEY
        self.active_key_id = active_key_id or cfg.KMS_KEY_ID or "default-v1"
        self._keyring: dict[str, str] = {}
        if keyring is None and cfg.KMS_KEYRING:
            try:
                keyring = json.loads(cfg.KMS_KEYRING)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("KMS_KEYRING must be a JSON object of key IDs to key values") from exc
        for key_id, material in (keyring or {}).items():
            if (not isinstance(key_id, str) or not key_id.strip()
                    or not isinstance(material, str) or len(material.encode("utf-8")) < 32):
                raise RuntimeError("every KMS_KEYRING entry needs an ID and 32+ byte key")
            self._keyring[key_id] = material
        if self._master_key:
            self._keyring.setdefault(self.active_key_id, self._master_key)

    def _key(self, tenant_id: str, key_id: str | None = None) -> bytes:
        key_id = key_id or self.active_key_id
        material = self._keyring.get(key_id, "")
        key_material = material.encode("utf-8")
        if (len(key_material) < 32 or "<" in material or ">" in material
                or "generate" in material.casefold()):
            raise RuntimeError("KMS_MASTER_KEY must contain at least 32 bytes")
        return HKDF(
            algorithm=SHA256(), length=32, salt=tenant_id.encode("utf-8"),
            info=f"FINESSE tenant provider credentials v2:{key_id}".encode("utf-8"),
        ).derive(key_material)

    def _legacy_key(self, tenant_id: str) -> bytes:
        legacy_material = self._keyring.get("default-v1", self._master_key)
        key_material = legacy_material.encode("utf-8")
        if (len(key_material) < 32 or "<" in legacy_material or ">" in legacy_material
                or "generate" in legacy_material.casefold()):
            raise RuntimeError("KMS_MASTER_KEY must contain at least 32 bytes")
        return HKDF(
            algorithm=SHA256(), length=32, salt=tenant_id.encode("utf-8"),
            info=b"FINESSE tenant provider credentials v1",
        ).derive(key_material)

    def put(self, tenant_id: str, name: str, secret: str) -> None:
        if not tenant_id.strip() or not name.strip() or not secret:
            raise ValueError("tenant_id, name, and secret are required")
        nonce = os.urandom(12)
        aad = f"v2:{tenant_id}:{name}:{self.active_key_id}".encode("utf-8")
        ciphertext = AESGCM(self._key(tenant_id)).encrypt(nonce, secret.encode("utf-8"), aad)
        envelope = "v2:" + self.active_key_id + ":" + base64.urlsafe_b64encode(
            nonce + ciphertext).decode("ascii")
        self.repository.put("tenant_secrets", tenant_id, name, {"envelope": envelope})

    def get(self, tenant_id: str, name: str) -> str | None:
        record = self.repository.get("tenant_secrets", tenant_id, name)
        if record is None:
            return None
        try:
            envelope = record["envelope"]
            if envelope.startswith("v2:"):
                _, key_id, encoded = envelope.split(":", 2)
                value = base64.urlsafe_b64decode(encoded.encode("ascii"))
                aad = f"v2:{tenant_id}:{name}:{key_id}".encode("utf-8")
                return AESGCM(self._key(tenant_id, key_id)).decrypt(
                    value[:12], value[12:], aad).decode("utf-8")
            # Read pre-kid envelopes until every tenant has been re-encrypted.
            value = base64.urlsafe_b64decode(envelope.encode("ascii"))
            return AESGCM(self._legacy_key(tenant_id)).decrypt(
                value[:12], value[12:],
                tenant_id.encode("utf-8") + b":" + name.encode("utf-8")).decode("utf-8")
        except (KeyError, ValueError, TypeError, binascii.Error, InvalidTag) as exc:
            raise RuntimeError("stored provider credential envelope cannot be decrypted") from exc

    def rotate_tenant(self, tenant_id: str) -> int:
        """Re-encrypt one tenant's credentials with the active key ID.

        Keep old key IDs in ``KMS_KEYRING`` until each tenant is rotated and
        backups containing old envelopes have expired.
        """
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        records = self.repository.list_items("tenant_secrets", tenant_id, limit=1000)
        rotated = 0
        for name, _record in records:
            secret = self.get(tenant_id, name)
            if secret is not None:
                self.put(tenant_id, name, secret)
                rotated += 1
        return rotated

    def delete(self, tenant_id: str, name: str) -> bool:
        return self.repository.delete("tenant_secrets", tenant_id, name)
