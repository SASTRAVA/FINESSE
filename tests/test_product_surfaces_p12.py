from io import BytesIO

import pytest
from docx import Document

from engine.billing.stripe_meters import LocalLedgerOnlyAdapter
from engine.db.storage import PlatformStorage
from engine.exports.deliverables import build_docx, resolve_verified_citations
from engine.portals.service import PortalService
from engine.voice.pipeline_policy import require_local_audio_provider, side_effect_disposition


def test_branded_docx_contains_sections_and_sensitivity_marking():
    data = build_docx(title="Pilot plan", summary="Summary", listen="Evidence",
                      shape="Options", deliver="Next step", sensitivity="confidential",
                      citations=[], tenant_name="Example")
    document = Document(BytesIO(data))
    assert "CONFIDENTIAL" in document.sections[0].header.paragraphs[0].text
    assert [paragraph.text for paragraph in document.paragraphs if paragraph.style.name.startswith("Heading")] == [
        "Pilot plan", "Executive Summary", "Listen", "Shape", "Deliver", "Verified Sources"]
    assert document.paragraphs[0].text == "Example"
    with pytest.raises(ValueError):
        build_docx(title="x", summary="", listen="", shape="", deliver="",
                   sensitivity="restricted", citations=[])


def test_docx_sources_are_tenant_acl_version_and_sensitivity_checked():
    records = {
        "doc-current": {"status": "ACTIVE", "current_version": 2, "lane": "general",
                         "sensitivity": "internal", "title": "Server title",
                         "source_type": "UPLOAD", "acl_principal_ids": ["alice"]},
        "doc-restricted": {"status": "ACTIVE", "current_version": 1, "lane": "general",
                            "sensitivity": "restricted", "title": "Secret"},
    }
    untrusted = [
        {"cite_id": "C1", "doc_id": "doc-current", "version": 2,
         "title": "Forged title", "source_type": "FORGED"},
        {"cite_id": "C2", "doc_id": "doc-current", "version": 1},
        {"cite_id": "C3", "doc_id": "doc-restricted", "version": 1},
    ]
    verified = resolve_verified_citations(
        untrusted, tenant_id="tenant-a", principal_id="alice",
        allowed_lanes=("general",), max_sensitivity="internal",
        get_document=lambda tenant, doc_id: records.get(doc_id) if tenant == "tenant-a" else None)
    assert verified == [{"cite_id": "C1", "doc_id": "doc-current", "version": 2,
                         "title": "Server title", "source_type": "UPLOAD"}]
    assert resolve_verified_citations(
        untrusted[:1], tenant_id="tenant-b", principal_id="alice",
        allowed_lanes=("general",), max_sensitivity="confidential",
        get_document=lambda tenant, doc_id: records.get(doc_id)
        if tenant == "tenant-a" else None) == []
    assert resolve_verified_citations(
        untrusted[:1], tenant_id="tenant-a", principal_id="bob",
        allowed_lanes=("general",), max_sensitivity="confidential",
        get_document=lambda _tenant, doc_id: records.get(doc_id)) == []
    document_bytes = build_docx(title="Plan", summary="Evidence [C1]", listen="",
                                shape="", deliver="", sensitivity="internal",
                                citations=verified)
    document = Document(BytesIO(document_bytes))
    assert any("[C1] Server title" in paragraph.text for paragraph in document.paragraphs)


def test_portal_snapshots_are_scoped_expiring_and_revocable():
    store = PlatformStorage(":memory:")
    service = PortalService(store)
    snapshot = service.publish("tenant", "client-a", {"text": "safe"},
                               sensitivity="public", publisher="admin")
    token = service.issue_access_token("tenant", "client-a", ttl_s=60)
    assert service.read("tenant", "client-a", token)[0]["snapshot_id"] == snapshot
    with pytest.raises(PermissionError):
        service.read("other-tenant", "client-a", token)
    service.revoke("tenant", "client-a", actor="admin")
    with pytest.raises(PermissionError):
        service.read("tenant", "client-a", token)
    with pytest.raises(PermissionError):
        service.publish("tenant", "restricted", {}, sensitivity="restricted", publisher="admin")
    with pytest.raises(PermissionError):
        service.publish("tenant", "confidential", {}, sensitivity="confidential",
                        publisher="admin", l4_override=True, publisher_tier=3)
    assert service.publish("tenant", "confidential-approved", {}, sensitivity="confidential",
                           publisher="admin", l4_override=True, publisher_tier=4)
    store.close()


def test_local_billing_adapter_is_idempotent_and_exports_csv():
    store = PlatformStorage(":memory:")
    billing = LocalLedgerOnlyAdapter(store)
    arguments = {"tenant_id": "tenant", "metric": "finesse_llm_tokens",
                 "quantity": 45, "window_hour": "2026-11-23T08"}
    assert billing.emit(**arguments)
    assert not billing.emit(**arguments)
    assert "finesse_llm_tokens,45" in billing.export_csv("tenant")
    store.close()


def test_voice_privacy_and_write_approval_policy():
    with pytest.raises(PermissionError):
        require_local_audio_provider("confidential", "cloud")
    require_local_audio_provider("confidential", "local")
    assert side_effect_disposition(True) == "gatekeeper_required"
