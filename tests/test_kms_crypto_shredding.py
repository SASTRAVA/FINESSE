from __future__ import annotations

import pytest

from engine.db.storage import PlatformStorage
from engine.security.kms_envelope import (
    LocalDevKMSProvider, TenantEnvelopeStore, TenantKeyShreddedError,
    TenantOffboardingService,
)


class DestroyableLocalProvider(LocalDevKMSProvider):
    def destroy_tenant_key(self, tenant_id, key_id):
        return True


def test_tenant_envelope_is_bound_and_crypto_shredded_per_tenant(tmp_path):
    repository = PlatformStorage(str(tmp_path / "kms.db"))
    provider = DestroyableLocalProvider("unit-test-master-key-material-000000000000")
    envelopes = TenantEnvelopeStore(repository, provider)
    tenant_a = envelopes.encrypt("tenant-a", "crm_contacts", "contact-7", "private-A")
    tenant_b = envelopes.encrypt("tenant-b", "crm_contacts", "contact-9", "private-B")
    assert envelopes.decrypt("tenant-a", "crm_contacts", "contact-7", tenant_a) == b"private-A"
    with pytest.raises(ValueError, match="authentication failed"):
        envelopes.decrypt("tenant-a", "crm_contacts", "another-record", tenant_a)

    result = envelopes.shred_tenant_key("tenant-a")
    assert result["shredded"] is True
    assert result["external_key_destroyed"] is True
    with pytest.raises(TenantKeyShreddedError):
        envelopes.decrypt("tenant-a", "crm_contacts", "contact-7", tenant_a)
    assert envelopes.decrypt("tenant-b", "crm_contacts", "contact-9", tenant_b) == b"private-B"


def test_offboarding_requires_same_tenant_l4_mfa_and_confirmation(tmp_path):
    repository = PlatformStorage(str(tmp_path / "offboard.db"))
    provider = DestroyableLocalProvider("unit-test-master-key-material-000000000000")
    envelopes = TenantEnvelopeStore(repository, provider)
    envelopes.encrypt("tenant-a", "secrets", "row-1", "secret")
    service = TenantOffboardingService(
        envelopes, repository, purge_qdrant=lambda tenant: tenant == "tenant-a",
        purge_vault=lambda tenant: tenant == "tenant-a")
    actor = {"sub": "ceo@example.test", "tenant_id": "tenant-a", "tier": 4,
             "amr": ["pwd", "mfa"]}
    with pytest.raises(PermissionError):
        service.offboard_and_crypto_shred(
            "tenant-a", actor, confirmation_token="wrong")
    result = service.offboard_and_crypto_shred(
        "tenant-a", actor, confirmation_token="SHRED:tenant-a:ceo@example.test")
    assert result["shredded"] is True
    assert result["vector_data_purged"] and result["vault_data_purged"]
