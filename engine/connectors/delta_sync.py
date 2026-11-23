"""Opt-in Google Drive and Microsoft Graph delta sync adapters."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx
import time

from ..config import cfg
from ..db.storage import PlatformStorage, storage
from ..rag.doc_lifecycle import DocumentLifecycle, document_lifecycle
from ..rag.ingest import ingest_text
from ..security.kms_envelope import TenantEnvelopeStore, tenant_envelope_store

MAX_CONNECTOR_DOCUMENT_BYTES = 8 * 1024 * 1024
GRAPH_ORIGIN = "https://graph.microsoft.com"


class ConnectorDisabled(RuntimeError):
    pass


class ConnectorSyncError(RuntimeError):
    pass


class EnterpriseConnector:
    provider = ""

    def __init__(self, repository: PlatformStorage = storage,
                 envelope_store: TenantEnvelopeStore = tenant_envelope_store,
                 lifecycle: DocumentLifecycle = document_lifecycle,
                 client: httpx.AsyncClient | None = None):
        self.repository, self.envelopes = repository, envelope_store
        self.lifecycle, self.client = lifecycle, client

    def configure(self, tenant_id: str, connector_id: str, *, access_token: str,
                  default_lane: str, sensitivity: str = "internal",
                  provider_options: dict | None = None) -> None:
        if not tenant_id or not connector_id or not access_token:
            raise ValueError("tenant, connector ID and OAuth access token are required")
        if default_lane not in {"coding", "prompt", "marketing", "bizdev", "exec",
                                "general", "security"}:
            raise ValueError("connector lane must be a recognized FINESSE lane")
        if sensitivity not in {"public", "internal", "confidential", "restricted"}:
            raise ValueError("unsupported connector sensitivity")
        options = provider_options or {}
        if (set(options) - {"drive_id"}
                or any(not isinstance(value, str) or not value or len(value) > 256
                       for value in options.values())):
            raise ValueError("only bounded, non-secret drive_id connector options are accepted")
        token_envelope = self.envelopes.encrypt(
            tenant_id, "connector_sync_states", connector_id, access_token)
        self.repository.put("connector_sync_states", tenant_id, connector_id, {
            "connector_id": connector_id, "provider": self.provider,
            "token_envelope": token_envelope, "delta_cursor": None,
            "default_lane": default_lane, "default_sensitivity": sensitivity,
            "options": options, "status": "ACTIVE",
        })

    def _state(self, tenant_id: str, connector_id: str) -> tuple[dict, str]:
        if cfg.DEPLOYMENT_MODE == "portable_ssd":
            raise ConnectorDisabled("cloud connectors are disabled in portable SSD mode")
        state = self.repository.get("connector_sync_states", tenant_id, connector_id)
        if not state or state.get("provider") != self.provider or state.get("status") != "ACTIVE":
            raise ConnectorDisabled("connector is not configured and active")
        token = self.envelopes.decrypt(
            tenant_id, "connector_sync_states", connector_id, state["token_envelope"])
        return state, token.decode("utf-8")

    def _http(self) -> tuple[httpx.AsyncClient, bool]:
        return (self.client, False) if self.client else (httpx.AsyncClient(timeout=30), True)

    async def _ingest(self, tenant_id: str, connector_id: str, state: dict,
                      external_id: str, title: str, raw: bytes, acl_ids: list[str]) -> None:
        if len(raw) > MAX_CONNECTOR_DOCUMENT_BYTES:
            raise ConnectorSyncError("connector file exceeds the 8 MiB limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConnectorSyncError("connector file is not UTF-8 text") from exc
        await ingest_text(
            text, title=title[:300], role=state["default_lane"], lane=state["default_lane"],
            sensitivity=state["default_sensitivity"], injected_by=f"connector:{connector_id}",
            source=self.provider.lower(), tenant_id=tenant_id,
            external_id=external_id, acl_principal_ids=acl_ids)

    async def _tombstone(self, tenant_id: str, external_id: str, actor: str) -> None:
        source_type = "GDRIVE" if self.provider == "gdrive" else "SHAREPOINT"
        doc_id = self.lifecycle.document_id(tenant_id, source_type, external_id)
        if self.lifecycle.get(tenant_id, doc_id):
            await self.lifecycle.tombstone(tenant_id, doc_id, actor)

    async def sync(self, tenant_id: str, connector_id: str) -> dict:
        raise NotImplementedError


class GoogleDriveConnector(EnterpriseConnector):
    provider = "gdrive"
    _BASE = "https://www.googleapis.com/drive/v3"

    async def sync(self, tenant_id: str, connector_id: str) -> dict:
        state, token = self._state(tenant_id, connector_id)
        client, close = self._http()
        headers = {"Authorization": f"Bearer {token}"}
        cursor = state.get("delta_cursor")
        try:
            if not cursor:
                response = await client.get(f"{self._BASE}/changes/startPageToken",
                                            headers=headers)
                response.raise_for_status()
                cursor = response.json()["startPageToken"]
            response = await client.get(f"{self._BASE}/changes", headers=headers,
                                        params={"pageToken": cursor, "includeRemoved": "true",
                                                "fields": "nextPageToken,newStartPageToken,"
                                                         "changes(file(id,name,trashed),removed,fileId)"})
            response.raise_for_status()
            payload = response.json()
            changes = list(payload.get("changes", []))
            next_cursor = payload.get("newStartPageToken") or payload.get("nextPageToken")
            while payload.get("nextPageToken"):
                response = await client.get(f"{self._BASE}/changes", headers=headers,
                                            params={"pageToken": payload["nextPageToken"],
                                                    "includeRemoved": "true",
                                                    "fields": "nextPageToken,newStartPageToken,"
                                                             "changes(file(id,name,trashed),removed,fileId)"})
                response.raise_for_status()
                payload = response.json()
                changes.extend(payload.get("changes", []))
                next_cursor = payload.get("newStartPageToken") or next_cursor
            synced = removed = 0
            for change in changes:
                file = change.get("file") or {}
                file_id = str(file.get("id") or change.get("fileId") or "")
                if not file_id:
                    continue
                if change.get("removed") or file.get("trashed"):
                    await self._tombstone(tenant_id, file_id, f"connector:{connector_id}")
                    removed += 1
                    continue
                permissions_response = await client.get(
                    f"{self._BASE}/files/{file_id}/permissions", headers=headers,
                    params={"fields": "permissions(id,emailAddress,displayName,type,deleted)"})
                permissions_response.raise_for_status()
                acl_ids = sorted({str(item.get("emailAddress") or item.get("id", "")).casefold()
                                  for item in permissions_response.json().get("permissions", [])
                                  if not item.get("deleted") and
                                  (item.get("emailAddress") or item.get("id"))})
                if str(file.get("mimeType", "")).startswith("application/vnd.google-apps."):
                    content_response = await client.get(
                        f"{self._BASE}/files/{file_id}/export", headers=headers,
                        params={"mimeType": "text/plain"})
                else:
                    content_response = await client.get(
                        f"{self._BASE}/files/{file_id}", headers=headers,
                        params={"alt": "media"})
                content_response.raise_for_status()
                await self._ingest(tenant_id, connector_id, state, file_id,
                                   str(file.get("name") or file_id),
                                   content_response.content, acl_ids)
                synced += 1
            state["delta_cursor"] = next_cursor or cursor
            state["last_sync_at"] = time.time()
            self.repository.put("connector_sync_states", tenant_id, connector_id, state)
            return {"synced": synced, "removed": removed, "cursor_updated": True}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ConnectorSyncError("Google Drive delta sync failed; cursor was not advanced") from exc
        finally:
            if close:
                await client.aclose()


class SharePointConnector(EnterpriseConnector):
    provider = "sharepoint"

    async def sync(self, tenant_id: str, connector_id: str) -> dict:
        state, token = self._state(tenant_id, connector_id)
        client, close = self._http()
        headers = {"Authorization": f"Bearer {token}"}
        drive_id = str(state.get("options", {}).get("drive_id", "me"))
        cursor = state.get("delta_cursor")
        url = cursor or f"{GRAPH_ORIGIN}/v1.0/drives/{drive_id}/root/delta"
        synced = removed = 0
        next_cursor = cursor
        try:
            while url:
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com":
                    raise ConnectorSyncError("Microsoft Graph returned an unsafe delta URL")
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("value", []):
                    item_id = str(item.get("id", ""))
                    if not item_id:
                        continue
                    if item.get("@removed"):
                        await self._tombstone(tenant_id, item_id, f"connector:{connector_id}")
                        removed += 1
                        continue
                    permission_response = await client.get(
                        f"{GRAPH_ORIGIN}/v1.0/drives/{drive_id}/items/{item_id}/permissions",
                        headers=headers)
                    permission_response.raise_for_status()
                    acl_ids = set()
                    for permission in permission_response.json().get("value", []):
                        identities = [permission.get("grantedToV2") or {}]
                        identities.extend(permission.get("grantedToIdentitiesV2") or [])
                        for identity in identities:
                            email = identity.get("user", {}).get("email")
                            principal_id = identity.get("group", {}).get("id")
                            if email or principal_id:
                                acl_ids.add(str(email or principal_id).casefold())
                    content_response = await client.get(
                        f"{GRAPH_ORIGIN}/v1.0/drives/{drive_id}/items/{item_id}/content",
                        headers=headers)
                    content_response.raise_for_status()
                    await self._ingest(tenant_id, connector_id, state, item_id,
                                       str(item.get("name") or item_id),
                                       content_response.content, sorted(acl_ids))
                    synced += 1
                url = payload.get("@odata.nextLink")
                next_cursor = payload.get("@odata.deltaLink") or next_cursor
            state["delta_cursor"] = next_cursor or cursor
            state["last_sync_at"] = time.time()
            self.repository.put("connector_sync_states", tenant_id, connector_id, state)
            return {"synced": synced, "removed": removed, "cursor_updated": True}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ConnectorSyncError("Microsoft Graph delta sync failed; cursor was not advanced") from exc
        finally:
            if close:
                await client.aclose()
