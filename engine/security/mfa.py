"""Tenant-scoped TOTP MFA with encrypted seeds and single-use recovery codes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError

from ..db.storage import PlatformStorage, storage
from ..db.tenant_secrets import TenantSecretStore

TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1
ENROLLMENT_TTL_SECONDS = 600
RECOVERY_CODE_COUNT = 8
_ISSUER = "SASTRAVA FINESSE"
_HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def _counter_code(secret: bytes, counter: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** TOTP_DIGITS)).zfill(TOTP_DIGITS)


def _matching_counter(secret_b32: str, code: str, now: float) -> int | None:
    if not re.fullmatch(r"[0-9]{6}", code):
        return None
    padded = secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8)
    try:
        secret = base64.b32decode(padded, casefold=True)
    except (ValueError, base64.binascii.Error):
        return None
    current = int(now // TOTP_PERIOD_SECONDS)
    match: int | None = None
    for counter in range(max(0, current - TOTP_WINDOW), current + TOTP_WINDOW + 1):
        if hmac.compare_digest(_counter_code(secret, counter), code):
            match = counter if match is None else max(match, counter)
    return match


def _new_recovery_codes() -> list[str]:
    return [
        (value := secrets.token_hex(16).upper())[:16] + "-" + value[16:]
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def _normalize_recovery_code(code: str) -> str:
    normalized = code.strip().upper()
    if re.fullmatch(r"[A-F0-9]{16}-[A-F0-9]{16}", normalized):
        return normalized.replace("-", "")
    if re.fullmatch(r"[A-F0-9]{32}", normalized):
        return normalized
    return ""


class MFAService:
    """Local TOTP lifecycle. Secrets are encrypted with the existing tenant key store."""

    def __init__(self, repository: PlatformStorage = storage,
                 secret_store: TenantSecretStore | None = None):
        self.repository = repository
        self.secret_store = secret_store or TenantSecretStore(repository)

    @staticmethod
    def _validate_identity(tenant_id: str, email: str) -> tuple[str, str]:
        tenant = tenant_id.strip()
        subject = email.strip().casefold()
        if not tenant or not subject:
            raise ValueError("tenant_id and email are required")
        return tenant, subject

    @staticmethod
    def _secret_record_id(email: str) -> str:
        return email.casefold()

    def status(self, tenant_id: str, email: str) -> dict:
        tenant, subject = self._validate_identity(tenant_id, email)
        record = self.repository.get("user_mfa_factors", tenant,
                                     self._secret_record_id(subject))
        return {"enrolled": bool(record and record.get("enabled")),
                "pending": bool(record and not record.get("enabled")
                                and record.get("enrollment_expires_at", 0) > time.time())}

    def begin_enrollment(self, tenant_id: str, email: str) -> dict:
        tenant, subject = self._validate_identity(tenant_id, email)
        record_id = self._secret_record_id(subject)
        previous = self.repository.get("user_mfa_factors", tenant, record_id)
        if previous and previous.get("enabled"):
            raise ValueError("MFA is already enrolled")
        existing_secret = self.secret_store.get(tenant, f"mfa-totp:{subject}")
        if (previous and previous.get("enrollment_expires_at", 0) > time.time()
                and existing_secret):
            secret = existing_secret
        else:
            secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
            self.secret_store.put(tenant, f"mfa-totp:{subject}", secret)
            self.repository.put("user_mfa_factors", tenant, record_id, {
                "email": subject, "enabled": False, "last_counter": -1,
                "recovery_hashes": [],
                "enrollment_expires_at": time.time() + ENROLLMENT_TTL_SECONDS,
            })
        label = quote(f"{_ISSUER}:{subject}", safe="")
        uri = (f"otpauth://totp/{label}?secret={secret}&issuer={quote(_ISSUER)}"
               f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD_SECONDS}")
        return {"secret": secret, "provisioning_uri": uri,
                "expires_in": ENROLLMENT_TTL_SECONDS}

    def _locked_factor(self, connection, tenant: str, record_id: str):
        query = "SELECT data_json FROM user_mfa_factors WHERE tenant_id=? AND record_id=?"
        if self.repository._is_postgres:
            query += " FOR UPDATE"
        row = connection.execute(self.repository._sql(query), (tenant, record_id)).fetchone()
        if row is None:
            return None
        return self.repository._decode(row["data_json"])

    def _write_factor(self, connection, tenant: str, record_id: str, value: dict) -> None:
        query = "UPDATE user_mfa_factors SET data_json=?, updated_at=? WHERE tenant_id=? AND record_id=?"
        if self.repository._is_postgres:
            query = query.replace("data_json=?", "data_json=?::jsonb")
        cursor = connection.execute(self.repository._sql(query), (
            json.dumps(value, separators=(",", ":")), time.time(), tenant, record_id))
        if cursor.rowcount != 1:
            raise RuntimeError("MFA factor changed while completing the operation")

    def complete_enrollment(self, tenant_id: str, email: str, code: str,
                            *, now: float | None = None) -> list[str]:
        tenant, subject = self._validate_identity(tenant_id, email)
        record_id = self._secret_record_id(subject)
        secret = self.secret_store.get(tenant, f"mfa-totp:{subject}")
        if not secret:
            raise ValueError("MFA enrollment is not pending")
        current_time = time.time() if now is None else now
        counter = _matching_counter(secret, code, current_time)
        if counter is None:
            raise ValueError("invalid MFA code")
        codes = _new_recovery_codes()
        hashes = [_HASHER.hash(_normalize_recovery_code(value)) for value in codes]
        with self.repository.transaction(tenant) as connection:
            factor = self._locked_factor(connection, tenant, record_id)
            if (factor is None or factor.get("enabled")
                    or factor.get("enrollment_expires_at", 0) <= current_time
                    or counter <= factor.get("last_counter", -1)):
                raise ValueError("MFA enrollment is no longer valid")
            factor.update({"enabled": True, "last_counter": counter,
                           "recovery_hashes": hashes, "enrollment_expires_at": 0,
                           "enrolled_at": time.time()})
            self._write_factor(connection, tenant, record_id, factor)
        return codes

    def verify(self, tenant_id: str, email: str, code: str,
               *, now: float | None = None) -> bool:
        tenant, subject = self._validate_identity(tenant_id, email)
        record_id = self._secret_record_id(subject)
        try:
            secret = self.secret_store.get(tenant, f"mfa-totp:{subject}")
        except RuntimeError:
            secret = None
        counter = (_matching_counter(secret, code, time.time() if now is None else now)
                   if secret else None)
        recovery = _normalize_recovery_code(code)
        with self.repository.transaction(tenant) as connection:
            factor = self._locked_factor(connection, tenant, record_id)
            if factor is None or not factor.get("enabled"):
                return False
            if counter is not None and counter > factor.get("last_counter", -1):
                factor["last_counter"] = counter
                self._write_factor(connection, tenant, record_id, factor)
                return True
            if not recovery:
                return False
            hashes = factor.get("recovery_hashes", [])
            matched_index = None
            for index, value in enumerate(hashes):
                try:
                    if _HASHER.verify(value, recovery):
                        matched_index = index
                        break
                except (VerifyMismatchError, VerificationError, ValueError):
                    continue
            if matched_index is None:
                return False
            hashes.pop(matched_index)
            factor["recovery_hashes"] = hashes
            self._write_factor(connection, tenant, record_id, factor)
            return True

    def disable(self, tenant_id: str, email: str, code: str,
                *, now: float | None = None) -> bool:
        if not self.verify(tenant_id, email, code, now=now):
            return False
        tenant, subject = self._validate_identity(tenant_id, email)
        self.repository.delete("user_mfa_factors", tenant, self._secret_record_id(subject))
        self.secret_store.delete(tenant, f"mfa-totp:{subject}")
        return True


mfa_service = MFAService()
