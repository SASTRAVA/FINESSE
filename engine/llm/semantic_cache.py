"""Scope-enforced cache adapter; delegates vector search to an optional RedisVL backend."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class CacheScope:
    tenant_id: str
    lane: str
    sensitivity: str
    model_version: str
    prompt_version: str
    acl_scope_hash: str

    def __post_init__(self):
        if not all((self.tenant_id, self.lane, self.sensitivity, self.model_version,
                    self.prompt_version, self.acl_scope_hash)):
            raise ValueError("all six cache-isolation dimensions are required")

    def metadata(self) -> dict[str, str]:
        return self.__dict__.copy()


class SemanticCache:
    """Exact scoped cache locally; an injected RedisVL SemanticCache can supply search."""
    def __init__(self, backend=None):
        self.backend = backend
        self._local: dict[str, str] = {}

    @staticmethod
    def _key(query: str, scope: CacheScope) -> str:
        return hashlib.sha256((json.dumps(scope.metadata(), sort_keys=True) + "\0" + query)
                              .encode("utf-8")).hexdigest()

    async def get(self, query: str, scope: CacheScope) -> str | None:
        if scope.sensitivity == "restricted":
            return None
        key = self._key(query, scope)
        if self.backend is None:
            return self._local.get(key)
        record = await self.backend.get(key=key, filter_expression=scope.metadata())
        if not record or record.get("metadata") != scope.metadata():
            return None
        return record.get("response")

    async def set(self, query: str, response: str, scope: CacheScope, *, mutating: bool = False) -> None:
        if mutating or scope.sensitivity == "restricted":
            return
        key = self._key(query, scope)
        if self.backend is None:
            self._local[key] = response
        else:
            await self.backend.set(key=key, query=query, response=response,
                                   metadata=scope.metadata(), filter_expression=scope.metadata())
