"""Tenant-bound envelope encryption for provider credentials at rest."""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import cfg
from .storage import PlatformStorage, storage


class TenantSecretStore:
    def __init__(self, repository: PlatformStorage = storage, master_key: str | None = None):
        self.repository = repository
        self._master_key = master_key if master_key is not None else cfg.KMS_MASTER_KEY

    def _key(self, tenant_id: str) -> bytes:
        key_material = self._master_key.encode("utf-8")
        if (len(key_material) < 32 or "<" in self._master_key or ">" in self._master_key
                or "generate" in self._master_key.casefold()):
            raise RuntimeError("KMS_MASTER_KEY must contain at least 32 bytes")
        return HKDF(
            algorithm=SHA256(), length=32, salt=tenant_id.encode("utf-8"),
            info=b"FINESSE tenant provider credentials v1",
        ).derive(key_material)

    def put(self, tenant_id: str, name: str, secret: str) -> None:
        if not tenant_id.strip() or not name.strip() or not secret:
            raise ValueError("tenant_id, name, and secret are required")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key(tenant_id)).encrypt(
            nonce, secret.encode("utf-8"), tenant_id.encode("utf-8") + b":" + name.encode("utf-8"))
        envelope = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        self.repository.put("tenant_secrets", tenant_id, name, {"envelope": envelope})

    def get(self, tenant_id: str, name: str) -> str | None:
        record = self.repository.get("tenant_secrets", tenant_id, name)
        if record is None:
            return None
        try:
            value = base64.urlsafe_b64decode(record["envelope"].encode("ascii"))
            return AESGCM(self._key(tenant_id)).decrypt(
                value[:12], value[12:],
                tenant_id.encode("utf-8") + b":" + name.encode("utf-8")).decode("utf-8")
        except (KeyError, ValueError, TypeError, binascii.Error, InvalidTag) as exc:
            raise RuntimeError("stored provider credential envelope cannot be decrypted") from exc

    def delete(self, tenant_id: str, name: str) -> bool:
        return self.repository.delete("tenant_secrets", tenant_id, name)
