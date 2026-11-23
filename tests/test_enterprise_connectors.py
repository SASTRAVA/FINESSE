from __future__ import annotations

import asyncio

import httpx
import pytest
from unittest.mock import AsyncMock, patch

from engine.config import cfg
from engine.connectors.delta_sync import (
    ConnectorDisabled, GoogleDriveConnector,
)
from engine.db.storage import PlatformStorage
from engine.security.kms_envelope import LocalDevKMSProvider, TenantEnvelopeStore


def test_google_drive_delta_sync_encrypts_token_and_persists_cursor(tmp_path):
    repository = PlatformStorage(str(tmp_path / "connector.db"))
    envelopes = TenantEnvelopeStore(repository, LocalDevKMSProvider(
        "unit-test-master-key-material-000000000000"))
    connector = GoogleDriveConnector(repository, envelopes)
    connector.configure("tenant-a", "drive-1", access_token="secret-access-token",
                        default_lane="general", sensitivity="internal")
    state = repository.get("connector_sync_states", "tenant-a", "drive-1")
    assert "secret-access-token" not in str(state)
    assert envelopes.decrypt("tenant-a", "connector_sync_states", "drive-1",
                             state["token_envelope"]) == b"secret-access-token"

    def handler(request):
        if request.url.path.endswith("/changes/startPageToken"):
            return httpx.Response(200, json={"startPageToken": "cursor-0"})
        if request.url.path.endswith("/changes"):
            return httpx.Response(200, json={"newStartPageToken": "cursor-1", "changes": [
                {"file": {"id": "file-1", "name": "Roadmap", "mimeType": "text/plain"}},
                {"fileId": "deleted-1", "removed": True},
            ]})
        if request.url.path.endswith("/files/file-1/permissions"):
            return httpx.Response(200, json={"permissions": [
                {"emailAddress": "Alice@Example.Test", "type": "user"}]})
        if request.url.path.endswith("/files/file-1"):
            return httpx.Response(200, content=b"approved confidential roadmap")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector.client = client
    with patch("engine.connectors.delta_sync.ingest_text", new=AsyncMock()) as ingest, \
            patch.object(connector, "_tombstone", new=AsyncMock()) as tombstone:
        result = asyncio.run(connector.sync("tenant-a", "drive-1"))
        call = ingest.await_args.kwargs
        assert call["acl_principal_ids"] == ["alice@example.test"]
        assert call["external_id"] == "file-1"
        assert tombstone.await_count == 1
    assert result == {"synced": 1, "removed": 1, "cursor_updated": True}
    updated = repository.get("connector_sync_states", "tenant-a", "drive-1")
    assert updated["delta_cursor"] == "cursor-1"
    asyncio.run(client.aclose())


def test_connectors_are_disabled_in_portable_ssd_mode(tmp_path, monkeypatch):
    repository = PlatformStorage(str(tmp_path / "portable.db"))
    envelopes = TenantEnvelopeStore(
        repository, LocalDevKMSProvider("unit-test-master-key-material-000000000000"))
    connector = GoogleDriveConnector(repository, envelopes)
    connector.configure("tenant-a", "drive-1", access_token="token",
                        default_lane="general")
    monkeypatch.setattr(cfg, "DEPLOYMENT_MODE", "portable_ssd")
    with pytest.raises(ConnectorDisabled, match="portable SSD"):
        asyncio.run(connector.sync("tenant-a", "drive-1"))
