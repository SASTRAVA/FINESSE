"""Tenant DEK envelope encryption with local, AWS KMS, and BYOK wrappers.

The local provider is intended for development and portable installs. A shared
local KEK cannot erase ciphertext copies in old backups; production crypto-shred
requires a customer/KMS key whose lifecycle is controlled outside this process.
"""
from __future__ import annotations

import base64
import os
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import cfg
from ..db.storage import PlatformStorage, storage
from ..audit.pg_audit import audit_log


class TenantKeyShreddedError(RuntimeError):
    """Raised when tenant ciphertext can no longer be decrypted."""


class KMSProvider(Protocol):
    def generate_data_key(self, tenant_id: str, key_id: str) -> tuple[bytes, bytes]: ...
    def unwrap_data_key(self, tenant_id: str, key_id: str, wrapped: bytes) -> bytes: ...
    def destroy_tenant_key(self, tenant_id: str, key_id: str) -> bool: ...


class LocalDevKMSProvider:
    """AES-GCM wrapper using a process-external development master key."""

    def __init__(self, master_key: str | None = None):
        self.master_key = master_key if master_key is not None else cfg.KMS_MASTER_KEY

    def _kek(self, tenant_id: str, key_id: str) -> bytes:
        material = self.master_key.encode("utf-8")
        if len(material) < 32 or "<" in self.master_key:
            raise RuntimeError("KMS_MASTER_KEY must contain 32 or more non-placeholder bytes")
        return HKDF(algorithm=SHA256(), length=32, salt=tenant_id.encode(),
                    info=f"FINESSE tenant DEK wrap:{key_id}".encode()).derive(material)

    def generate_data_key(self, tenant_id: str, key_id: str) -> tuple[bytes, bytes]:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        wrapped = nonce + AESGCM(self._kek(tenant_id, key_id)).encrypt(
            nonce, dek, f"{tenant_id}:{key_id}".encode())
        return dek, wrapped

    def unwrap_data_key(self, tenant_id: str, key_id: str, wrapped: bytes) -> bytes:
        if len(wrapped) < 29:
            raise ValueError("wrapped DEK is malformed")
        return AESGCM(self._kek(tenant_id, key_id)).decrypt(
            wrapped[:12], wrapped[12:], f"{tenant_id}:{key_id}".encode())

    def destroy_tenant_key(self, tenant_id: str, key_id: str) -> bool:
        # Shared development KEKs cannot provide backup-safe crypto-shredding.
        return False


class AwsKMSProvider:
    """AWS KMS GenerateDataKey/Decrypt adapter; boto3 is loaded only when used."""

    def __init__(self, key_arn: str, client=None):
        if not key_arn:
            raise ValueError("AWS KMS key ARN is required")
        if client is None:
            import boto3
            client = boto3.client("kms")
        self.key_arn = key_arn
        self.client = client

    @staticmethod
    def _context(tenant_id: str, key_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id, "key_id": key_id, "service": "FINESSE"}

    def generate_data_key(self, tenant_id: str, key_id: str) -> tuple[bytes, bytes]:
        result = self.client.generate_data_key(
            KeyId=self.key_arn, KeySpec="AES_256",
            EncryptionContext=self._context(tenant_id, key_id))
        return result["Plaintext"], result["CiphertextBlob"]

    def unwrap_data_key(self, tenant_id: str, key_id: str, wrapped: bytes) -> bytes:
        result = self.client.decrypt(
            KeyId=self.key_arn, CiphertextBlob=wrapped,
            EncryptionContext=self._context(tenant_id, key_id))
        return result["Plaintext"]

    def destroy_tenant_key(self, tenant_id: str, key_id: str) -> bool:
        # AWS KMS key deletion is asynchronous; alias removal alone is not erasure.
        return False


class BYOKWrapperProvider:
    """Adapter for a customer KMS with GenerateDataKey/Decrypt-compatible calls."""

    def __init__(self, key_uri: str, client):
        if not key_uri or client is None:
            raise ValueError("BYOK key URI and KMS client are required")
        self.key_uri, self.client = key_uri, client

    def generate_data_key(self, tenant_id: str, key_id: str) -> tuple[bytes, bytes]:
        result = self.client.generate_data_key(
            KeyId=self.key_uri, KeySpec="AES_256",
            EncryptionContext={"tenant_id": tenant_id, "key_id": key_id})
        return result["Plaintext"], result["CiphertextBlob"]

    def unwrap_data_key(self, tenant_id: str, key_id: str, wrapped: bytes) -> bytes:
        return self.client.decrypt(
            KeyId=self.key_uri, CiphertextBlob=wrapped,
            EncryptionContext={"tenant_id": tenant_id, "key_id": key_id})["Plaintext"]

    def destroy_tenant_key(self, tenant_id: str, key_id: str) -> bool:
        destroy = getattr(self.client, "destroy_tenant_key", None)
        return bool(destroy and destroy(self.key_uri, tenant_id, key_id))


@dataclass
class _CachedDEK:
    value: bytearray
    expires_at: float


class TenantEnvelopeStore:
    def __init__(self, repository: PlatformStorage = storage,
                 provider: KMSProvider | None = None, *, cache_ttl: int = 60,
                 cache_capacity: int = 100):
        if not 1 <= cache_ttl <= 60 or cache_capacity < 1:
            raise ValueError("DEK cache must be bounded to at most 60 seconds")
        self.repository = repository
        self.provider = provider or LocalDevKMSProvider()
        self.cache_ttl, self.cache_capacity = cache_ttl, cache_capacity
        self._cache: OrderedDict[tuple[str, str], _CachedDEK] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value.encode("ascii"))

    def _key_record(self, tenant_id: str, *, create: bool) -> dict:
        record = self.repository.get("tenant_encryption_keys", tenant_id, "active")
        if record:
            if record.get("status") == "SHREDDED":
                raise TenantKeyShreddedError("tenant encryption key has been shredded")
            return record
        if not create:
            raise TenantKeyShreddedError("tenant encryption key is unavailable")
        key_id = "tenant-dek-v1"
        dek, wrapped = self.provider.generate_data_key(tenant_id, key_id)
        record = {"key_id": key_id, "key_version": 1,
                  "provider": type(self.provider).__name__,
                  "wrapped_dek": self._encode(wrapped), "status": "ACTIVE",
                  "created_at": time.time()}
        try:
            inserted = self.repository.put_if_absent(
                "tenant_encryption_keys", tenant_id, "active", record)
        finally:
            # Do not retain the newly generated plaintext key outside the bounded cache.
            dek = b"\x00" * len(dek)
        if not inserted:
            return self._key_record(tenant_id, create=False)
        return record

    def _dek(self, tenant_id: str, record: dict) -> bytes:
        cache_key = (tenant_id, str(record["key_id"]))
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached.expires_at > now:
                self._cache.move_to_end(cache_key)
                return bytes(cached.value)
            if cached:
                self._wipe(cached.value)
                del self._cache[cache_key]
        key = self.provider.unwrap_data_key(
            tenant_id, record["key_id"], self._decode(record["wrapped_dek"]))
        if len(key) != 32:
            raise RuntimeError("KMS returned a non-AES-256 data key")
        with self._lock:
            self._cache[cache_key] = _CachedDEK(bytearray(key), now + self.cache_ttl)
            while len(self._cache) > self.cache_capacity:
                _, evicted = self._cache.popitem(last=False)
                self._wipe(evicted.value)
        return key

    @staticmethod
    def _wipe(value: bytearray) -> None:
        for index in range(len(value)):
            value[index] = 0

    def encrypt(self, tenant_id: str, table: str, record_id: str, plaintext: bytes | str
                ) -> dict:
        if not tenant_id or not table or not record_id:
            raise ValueError("tenant, table, and record identifiers are required")
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else bytes(plaintext)
        record = self._key_record(tenant_id, create=True)
        nonce = os.urandom(12)
        aad = f"{tenant_id}|{table}|{record_id}|{record['key_version']}".encode()
        ciphertext = AESGCM(self._dek(tenant_id, record)).encrypt(nonce, data, aad)
        return {"algorithm": "AES-256-GCM", "key_id": record["key_id"],
                "key_version": record["key_version"], "nonce": self._encode(nonce),
                "ciphertext": self._encode(ciphertext)}

    def decrypt(self, tenant_id: str, table: str, record_id: str, envelope: dict) -> bytes:
        record = self._key_record(tenant_id, create=False)
        if (envelope.get("algorithm") != "AES-256-GCM"
                or envelope.get("key_id") != record.get("key_id")
                or envelope.get("key_version") != record.get("key_version")):
            raise ValueError("encrypted payload key metadata does not match tenant key")
        aad = f"{tenant_id}|{table}|{record_id}|{record['key_version']}".encode()
        try:
            return AESGCM(self._dek(tenant_id, record)).decrypt(
                self._decode(envelope["nonce"]), self._decode(envelope["ciphertext"]), aad)
        except (InvalidTag, KeyError, ValueError) as exc:
            raise ValueError("encrypted payload authentication failed") from exc

    def shred_tenant_key(self, tenant_id: str) -> dict:
        record = self.repository.get("tenant_encryption_keys", tenant_id, "active")
        if not record:
            return {"shredded": False, "reason": "no active tenant key"}
        destroyed = self.provider.destroy_tenant_key(tenant_id, record["key_id"])
        record.update({"status": "SHREDDED", "wrapped_dek": None,
                       "shredded_at": time.time(), "external_key_destroyed": destroyed})
        self.repository.put("tenant_encryption_keys", tenant_id, "active", record)
        with self._lock:
            cached = self._cache.pop((tenant_id, str(record["key_id"])), None)
            if cached:
                self._wipe(cached.value)
        return {"shredded": True, "external_key_destroyed": destroyed,
                "key_version": record["key_version"]}


class TenantOffboardingService:
    def __init__(self, envelope_store: TenantEnvelopeStore,
                 repository: PlatformStorage = storage,
                 *, purge_qdrant: Callable[[str], object] | None = None,
                 purge_vault: Callable[[str], object] | None = None):
        self.envelope_store, self.repository = envelope_store, repository
        self.purge_qdrant, self.purge_vault = purge_qdrant, purge_vault

    def offboard_and_crypto_shred(self, tenant_id: str, actor: dict, *,
                                  confirmation_token: str) -> dict:
        if (actor.get("tier", 0) < 4 or "mfa" not in actor.get("amr", [])
                or actor.get("tenant_id") != tenant_id):
            raise PermissionError("offboarding requires a same-tenant MFA-authenticated L4 actor")
        if not secrets.compare_digest(confirmation_token,
                                      f"SHRED:{tenant_id}:{actor.get('sub', '')}"):
            raise PermissionError("explicit tenant-scoped crypto-shred confirmation is required")
        for name, record in self.repository.list_items("scim_tokens", tenant_id, limit=1000):
            record["revoked_at"] = time.time()
            self.repository.put("scim_tokens", tenant_id, name, record)
        for name, _record in self.repository.list_items("ws_tickets", tenant_id, limit=1000):
            self.repository.delete("ws_tickets", tenant_id, name)
        for name, record in self.repository.list_items("auth_sessions", tenant_id, limit=1000):
            record["status"] = "REVOKED"
            self.repository.put("auth_sessions", tenant_id, name, record)
            self.repository.put("revoked_sessions", tenant_id, name, {
                "status": "REVOKED", "sub": record.get("sub"),
                "expires_at": record.get("expires_at", int(time.time())),
            })
        vector_purged = bool(self.purge_qdrant and self.purge_qdrant(tenant_id))
        vault_purged = bool(self.purge_vault and self.purge_vault(tenant_id))
        shredded = self.envelope_store.shred_tenant_key(tenant_id)
        self.repository.put("tenant_identity_settings", tenant_id, "offboarding_tombstone", {
            "offboarded_at": time.time(), "actor": actor.get("sub"),
            "pii": False, "key_version": shredded.get("key_version"),
        })
        audit_log.append(tenant_id, {"action": "tenant_crypto_shredded",
                                     "actor": actor.get("sub"),
                                     "key_version": shredded.get("key_version")})
        return {"sessions_revoked": True, "scim_tokens_revoked": True,
                "vector_data_purged": vector_purged, "vault_data_purged": vault_purged,
                **shredded}


tenant_envelope_store = TenantEnvelopeStore()
