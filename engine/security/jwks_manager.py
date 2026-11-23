"""kid-aware EdDSA signing, JWKS publication, rotation, and JWT verification."""
from __future__ import annotations

import base64
import json
import secrets
import time
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..config import cfg
from ..db.storage import PlatformStorage, storage
from ..db.tenant_secrets import TenantSecretStore

_KEY_TENANT = "default"
_POINTER_ID = "__active_signing_key__"
_ISSUER = "https://sastrava.com/finesse"
_AUDIENCE = "finesse-api"
_ROTATION_GRACE_SECONDS = 15 * 60


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((4 - len(value) % 4) % 4))


class JWTKeyError(ValueError):
    """A signing or verification key is missing, expired, or invalid."""


class JWKSManager:
    def __init__(self, repository: PlatformStorage = storage,
                 secret_store: TenantSecretStore | None = None,
                 *, issuer: str = _ISSUER, audience: str = _AUDIENCE):
        self.repository = repository
        self.secret_store = secret_store or TenantSecretStore(repository)
        self.issuer = issuer
        self.audience = audience

    def _new_key(self, status: str = "VERIFY_ONLY") -> dict:
        private = Ed25519PrivateKey.generate()
        kid = secrets.token_urlsafe(12)
        private_pem = private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")
        public_raw = private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        now = time.time()
        record = {
            "kid": kid,
            "algorithm": "EdDSA",
            "public_jwk": {"kty": "OKP", "crv": "Ed25519", "x": _b64url(public_raw),
                           "use": "sig", "alg": "EdDSA", "kid": kid},
            "status": status,
            "valid_from": now,
            "valid_until": None,
            "created_at": now,
        }
        self.secret_store.put(_KEY_TENANT, f"jwks-private:{kid}", private_pem)
        try:
            self.repository.put("jwks_signing_keys", _KEY_TENANT, kid, record)
        except Exception:
            self.secret_store.delete(_KEY_TENANT, f"jwks-private:{kid}")
            raise
        return record

    def _pointer(self) -> dict | None:
        return self.repository.get("jwks_signing_keys", _KEY_TENANT, _POINTER_ID)

    def _ensure_active(self) -> dict:
        pointer = self._pointer()
        if pointer:
            active = self.repository.get("jwks_signing_keys", _KEY_TENANT,
                                         pointer.get("kid", ""))
            if active and active.get("status") == "ACTIVE":
                return active
            raise JWTKeyError("active JWT signing key is missing or invalid")
        candidate = self._new_key("ACTIVE")
        created = self.repository.put_if_absent(
            "jwks_signing_keys", _KEY_TENANT, _POINTER_ID,
            {"kid": candidate["kid"], "created_at": time.time()})
        if not created:
            self.repository.put("jwks_signing_keys", _KEY_TENANT, candidate["kid"],
                                {**candidate, "status": "RETIRED"})
            self.secret_store.delete(_KEY_TENANT, f"jwks-private:{candidate['kid']}")
            pointer = self._pointer()
            active = self.repository.get("jwks_signing_keys", _KEY_TENANT,
                                         pointer.get("kid", "") if pointer else "")
            if not active or active.get("status") != "ACTIVE":
                raise JWTKeyError("JWT signing key initialization raced without an active key")
            return active
        return candidate

    @staticmethod
    def _claims(payload: dict, issuer: str, audience: str) -> dict:
        claims = dict(payload)
        claims["iss"] = issuer
        claims["aud"] = audience
        now = int(time.time())
        claims.setdefault("iat", now)
        claims.setdefault("nbf", now)
        claims.setdefault("jti", secrets.token_urlsafe(18))
        return claims

    def sign(self, payload: dict) -> str:
        active = self._ensure_active()
        private_pem = self.secret_store.get(
            _KEY_TENANT, f"jwks-private:{active['kid']}")
        if not private_pem:
            raise JWTKeyError("active JWT signing key material is unavailable")
        private = serialization.load_pem_private_key(private_pem.encode("ascii"), password=None)
        if not isinstance(private, Ed25519PrivateKey):
            raise JWTKeyError("active JWT signing key is not Ed25519")
        claims = self._claims(payload, self.issuer, self.audience)
        return jwt.encode(claims, private, algorithm="EdDSA",
                          headers={"kid": active["kid"], "typ": "JWT"})

    def verify(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid or header.get("alg") != "EdDSA":
                raise JWTKeyError("JWT header is missing a supported key ID")
            record = self.repository.get("jwks_signing_keys", _KEY_TENANT, kid)
            now = time.time()
            if (not record or record.get("algorithm") != "EdDSA"
                    or record.get("status") not in {"ACTIVE", "VERIFY_ONLY"}
                    or record.get("valid_from", now + 1) > now
                    or (record.get("valid_until") is not None
                        and record["valid_until"] <= now)):
                raise JWTKeyError("JWT signing key is unknown or outside its validity window")
            jwk = record["public_jwk"]
            if (jwk.get("kid") != kid or jwk.get("alg") != "EdDSA"
                    or jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519"):
                raise JWTKeyError("JWT public key metadata is invalid")
            public_key = Ed25519PublicKey.from_public_bytes(_unb64url(jwk["x"]))
            return jwt.decode(
                token, public_key, algorithms=["EdDSA"], audience=self.audience,
                issuer=self.issuer,
                options={"require": ["sub", "role", "tier", "tenant_id", "amr",
                                     "iss", "aud", "iat", "nbf", "exp", "jti"]},
            )
        except JWTKeyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise JWTKeyError("JWT verification failed") from exc

    def jwks(self, *, now: float | None = None) -> dict:
        current = time.time() if now is None else now
        records = self.repository.list("jwks_signing_keys", _KEY_TENANT, limit=1000)
        keys = [record["public_jwk"] for record in records
                if record.get("record_id") != _POINTER_ID
                and record.get("status") in {"ACTIVE", "VERIFY_ONLY"}
                and record.get("valid_from", current + 1) <= current
                and (record.get("valid_until") is None
                     or record["valid_until"] > current)]
        return {"keys": sorted(keys, key=lambda value: value["kid"])}

    def publish_rotation_key(self) -> dict:
        """Publish K2 as verify-only while K1 remains the active signer."""
        self._ensure_active()
        return self._new_key("VERIFY_ONLY")

    def activate_rotation_key(self, kid: str, *, now: float | None = None) -> dict:
        current_time = time.time() if now is None else now
        candidate = self.repository.get("jwks_signing_keys", _KEY_TENANT, kid)
        if not candidate or candidate.get("status") != "VERIFY_ONLY":
            raise JWTKeyError("rotation key must be published before activation")
        if not self.secret_store.get(_KEY_TENANT, f"jwks-private:{kid}"):
            raise JWTKeyError("rotation key private material is unavailable")
        with self.repository.transaction(_KEY_TENANT) as connection:
            pointer_query = ("SELECT data_json FROM jwks_signing_keys WHERE tenant_id=? "
                             "AND record_id=?")
            if self.repository._is_postgres:
                pointer_query += " FOR UPDATE"
            pointer_row = connection.execute(self.repository._sql(pointer_query),
                                             (_KEY_TENANT, _POINTER_ID)).fetchone()
            if pointer_row is None:
                raise JWTKeyError("active JWT signer is not initialized")
            pointer = self.repository._decode(pointer_row["data_json"])
            previous_kid = pointer.get("kid")
            old = self._record_for_update(connection, previous_kid)
            new = self._record_for_update(connection, kid)
            if not old or old.get("status") != "ACTIVE" or not new:
                raise JWTKeyError("rotation state changed during activation")
            old["status"] = "VERIFY_ONLY"
            old["valid_until"] = (current_time + cfg.ACCESS_TOKEN_EXPIRE_MINUTES * 60
                                   + _ROTATION_GRACE_SECONDS)
            new["status"] = "ACTIVE"
            new["valid_until"] = None
            pointer["kid"] = kid
            self._write_record(connection, previous_kid, old)
            self._write_record(connection, kid, new)
            self._write_record(connection, _POINTER_ID, pointer)
        return {"active_kid": kid, "previous_kid": previous_kid,
                "previous_valid_until": old["valid_until"]}

    def _record_for_update(self, connection, record_id: str):
        query = "SELECT data_json FROM jwks_signing_keys WHERE tenant_id=? AND record_id=?"
        if self.repository._is_postgres:
            query += " FOR UPDATE"
        row = connection.execute(self.repository._sql(query),
                                 (_KEY_TENANT, record_id)).fetchone()
        return self.repository._decode(row["data_json"]) if row else None

    def _write_record(self, connection, record_id: str, value: dict) -> None:
        query = ("UPDATE jwks_signing_keys SET data_json=?, updated_at=? "
                 "WHERE tenant_id=? AND record_id=?")
        if self.repository._is_postgres:
            query = query.replace("data_json=?", "data_json=?::jsonb")
        cursor = connection.execute(self.repository._sql(query), (
            json.dumps(value, separators=(",", ":")), time.time(), _KEY_TENANT, record_id))
        if cursor.rowcount != 1:
            raise JWTKeyError("rotation key record disappeared")

    def retire_expired(self, *, now: float | None = None) -> list[str]:
        current = time.time() if now is None else now
        retired = []
        for record_id, record in self.repository.list_items(
                "jwks_signing_keys", _KEY_TENANT, limit=1000):
            if (record_id == _POINTER_ID or record.get("status") != "VERIFY_ONLY"
                    or record.get("valid_until") is None
                    or record["valid_until"] > current):
                continue
            record["status"] = "RETIRED"
            self.repository.put("jwks_signing_keys", _KEY_TENANT, record_id, record)
            self.secret_store.delete(_KEY_TENANT, f"jwks-private:{record_id}")
            retired.append(record_id)
        return retired

    def revoke_session(self, payload: dict) -> bool:
        tenant_id = payload.get("tenant_id")
        jti = payload.get("jti")
        expires_at = payload.get("exp")
        if (not isinstance(tenant_id, str) or not tenant_id or not isinstance(jti, str)
                or not jti or not isinstance(expires_at, int)):
            return False
        if expires_at <= int(time.time()):
            return True
        self.repository.put("revoked_sessions", tenant_id, jti, {
            "status": "REVOKED", "sub": payload.get("sub"),
            "expires_at": expires_at,
        })
        return True


jwks_manager = JWKSManager()
