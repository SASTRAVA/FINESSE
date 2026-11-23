"""Pinned MCP manifest and destination policy checks for future remote plugins."""
from __future__ import annotations

import hashlib
import hmac
import json

from ..network_safety import validate_public_target_url


class ManifestRejected(ValueError):
    pass


class PinnedManifest:
    def __init__(self):
        self._pins: dict[tuple[str, str], str] = {}

    @staticmethod
    def digest(tools: list[dict]) -> str:
        canonical = json.dumps(tools, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def approve(self, tenant_id: str, server_name: str, tools: list[dict]) -> str:
        digest = self.digest(tools)
        self._pins[(tenant_id, server_name)] = digest
        return digest

    def verify(self, tenant_id: str, server_name: str, tools: list[dict], *,
               sensitivity: str, sovereign_vpc_verified: bool = False) -> None:
        pinned = self._pins.get((tenant_id, server_name))
        if not pinned or not hmac.compare_digest(pinned, self.digest(tools)):
            raise ManifestRejected("MCP tool manifest is unpinned or changed")
        if sensitivity in {"confidential", "restricted"} and not sovereign_vpc_verified:
            raise ManifestRejected("external MCP is not authorized for sensitive data")

    @staticmethod
    def validate_destination(url: str) -> tuple[str, ...]:
        return validate_public_target_url(url)


pinned_manifests = PinnedManifest()
