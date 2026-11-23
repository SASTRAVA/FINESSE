import time

import pytest

from engine.compliance.services import ComplianceService
from engine.db.storage import PlatformStorage
from engine.feature_flags import KillSwitches


def test_consent_withdrawal_and_dsar_tracking_are_tenant_scoped():
    store = PlatformStorage(":memory:")
    service = ComplianceService(store)
    consent = service.grant_consent("tenant-a", "principal-1", "analytics", "notice-1")
    withdrawn = service.withdraw_consent("tenant-a", consent["id"], actor="principal-1")
    assert withdrawn["status"] == "WITHDRAWN"
    assert store.get("consent_records", "tenant-b", consent["id"]) is None
    dsar = service.create_dsar("tenant-a", "principal-1", "ERASURE")
    assert dsar["sla_due_at"] - dsar["submitted_at"] == 90 * 86400
    store.close()


def test_breach_deadline_and_retention_floor_are_explicit():
    store = PlatformStorage(":memory:")
    service = ComplianceService(store)
    incident = service.create_breach_incident("tenant", "high", 4)
    assert incident["report_due_at"] - incident["discovered_at"] == 72 * 3600
    store.put("llm_usage_ledger", "tenant", "old", {"created_at": time.time() - 400 * 86400})
    assert service.retention_candidates("tenant")
    with pytest.raises(ValueError):
        service.retention_candidates("tenant", minimum_days=30)
    assert store.get("llm_usage_ledger", "tenant", "old") is not None
    store.close()


def test_global_kill_switch_override_and_tenant_override():
    store = PlatformStorage(":memory:")
    flags = KillSwitches(store)
    assert flags.enabled("cloud_llm_egress_enabled", "tenant")
    flags.set("cloud_llm_egress_enabled", False, actor="admin", reason="incident")
    assert not flags.enabled("cloud_llm_egress_enabled", "tenant")
    flags.set("cloud_llm_egress_enabled", True, tenant_id="tenant",
              actor="admin", reason="recovery")
    assert flags.enabled("cloud_llm_egress_enabled", "tenant")
    store.close()
