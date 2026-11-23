"""Append-only per-tenant audit chain for security-sensitive application events."""
from __future__ import annotations

import hashlib
import json
import time
import uuid

from ..db.storage import PlatformStorage, storage

_ZERO_HASH = "0" * 64


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


class HashChainedAuditLog:
    def __init__(self, repository: PlatformStorage = storage):
        self.repository = repository

    def append(self, tenant_id: str, payload: dict) -> dict:
        if not tenant_id.strip() or not isinstance(payload, dict) or not payload:
            raise ValueError("tenant_id and a non-empty audit payload are required")
        event_id = uuid.uuid4().hex
        created_at = time.time()
        with self.repository.transaction(tenant_id) as connection:
            if not self.repository._is_postgres:
                connection.execute(
                    "INSERT OR IGNORE INTO audit_heads(tenant_id, sequence, current_hash) "
                    "VALUES (?, 0, ?)", (tenant_id, _ZERO_HASH))
            else:
                connection.execute(
                    "INSERT INTO audit_heads(tenant_id, sequence, current_hash) "
                    "VALUES (?, 0, ?) ON CONFLICT (tenant_id) DO NOTHING",
                    (tenant_id, _ZERO_HASH))
            head_query = "SELECT sequence, current_hash FROM audit_heads WHERE tenant_id=?"
            if self.repository._is_postgres:
                head_query += " FOR UPDATE"
            head = connection.execute(self.repository._sql(head_query), (tenant_id,)).fetchone()
            sequence = int(head["sequence"]) + 1
            previous_hash = str(head["current_hash"])
            envelope = {"tenant_id": tenant_id, "sequence": sequence,
                        "event_id": event_id, "previous_hash": previous_hash,
                        "created_at": created_at, "payload": payload}
            event_hash = hashlib.sha256(_canonical(envelope)).hexdigest()
            data = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
            insert = (
                "INSERT INTO audit_events(tenant_id, sequence, event_id, previous_hash, "
                "event_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            )
            if self.repository._is_postgres:
                insert = insert.replace(
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", "VALUES (?, ?, ?, ?, ?, ?::jsonb, ?)")
            connection.execute(self.repository._sql(insert),
                (tenant_id, sequence, event_id, previous_hash, event_hash, data, created_at))
            connection.execute(self.repository._sql(
                "UPDATE audit_heads SET sequence=?, current_hash=? WHERE tenant_id=?"),
                (sequence, event_hash, tenant_id))
        return {**envelope, "event_hash": event_hash}

    def verify(self, tenant_id: str) -> bool:
        if not tenant_id.strip():
            raise ValueError("tenant_id is required")
        with self.repository.transaction(tenant_id) as connection:
            rows = connection.execute(self.repository._sql(
                "SELECT sequence, event_id, previous_hash, event_hash, payload_json, created_at "
                "FROM audit_events WHERE tenant_id=? ORDER BY sequence"),
                (tenant_id,)).fetchall()
            head = connection.execute(self.repository._sql(
                "SELECT sequence, current_hash FROM audit_heads WHERE tenant_id=?"),
                (tenant_id,)).fetchone()
        previous_hash = _ZERO_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            payload_value = row["payload_json"]
            payload = json.loads(payload_value) if isinstance(payload_value, str) else payload_value
            envelope = {"tenant_id": tenant_id, "sequence": expected_sequence,
                        "event_id": row["event_id"], "previous_hash": previous_hash,
                        "created_at": row["created_at"], "payload": payload}
            event_hash = hashlib.sha256(_canonical(envelope)).hexdigest()
            if (int(row["sequence"]) != expected_sequence
                    or row["previous_hash"] != previous_hash
                    or row["event_hash"] != event_hash):
                return False
            previous_hash = event_hash
        if not rows:
            return head is None or (int(head["sequence"]) == 0
                                    and head["current_hash"] == _ZERO_HASH)
        return (head is not None and int(head["sequence"]) == len(rows)
                and head["current_hash"] == previous_hash)


audit_log = HashChainedAuditLog()
