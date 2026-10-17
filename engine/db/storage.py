"""Small tenant-scoped SQLite repository with a PostgreSQL RLS migration companion."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Iterator

from ..config import cfg

TABLES = (
    "tenants", "users", "services", "icps", "campaigns", "companies", "contacts",
    "leads", "lead_campaigns", "email_messages", "email_events", "calls",
    "consent_records", "suppression_entries", "activities", "meetings", "jobs",
    "audit_logs", "gatekeeper_approvals", "scan_tasks", "scan_findings",
    "scan_evidence", "catalog_repositories",
)


class PlatformStorage:
    """JSON-record repository; every read/write requires an explicit tenant ID."""

    def __init__(self, path: str | None = None):
        database = path or str(cfg.DATA / "platform.db")
        self._connection = sqlite3.connect(database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            for table in TABLES:
                self._connection.execute(
                    f'CREATE TABLE IF NOT EXISTS "{table}" ('
                    "tenant_id TEXT NOT NULL, record_id TEXT NOT NULL, "
                    "data_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
                    "PRIMARY KEY (tenant_id, record_id))")
                self._connection.execute(
                    f'CREATE INDEX IF NOT EXISTS "idx_{table}_tenant" '
                    f'ON "{table}" (tenant_id)')
            self._connection.commit()

    @staticmethod
    def _validate(table: str, tenant_id: str) -> None:
        if table not in TABLES:
            raise ValueError("unknown platform table")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._connection
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def put(self, table: str, tenant_id: str, record_id: str, value: dict) -> dict:
        self._validate(table, tenant_id)
        if not record_id:
            raise ValueError("record_id is required")
        now = time.time()
        payload = dict(value)
        payload["tenant_id"] = tenant_id
        with self.transaction() as connection:
            connection.execute(
                f'INSERT INTO "{table}" (tenant_id, record_id, data_json, created_at, updated_at) '
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(tenant_id, record_id) DO UPDATE SET "
                "data_json=excluded.data_json, updated_at=excluded.updated_at",
                (tenant_id, record_id, json.dumps(payload, separators=(",", ":")), now, now))
        return payload

    def get(self, table: str, tenant_id: str, record_id: str) -> dict | None:
        self._validate(table, tenant_id)
        with self._lock:
            row = self._connection.execute(
                f'SELECT data_json FROM "{table}" WHERE tenant_id=? AND record_id=?',
                (tenant_id, record_id)).fetchone()
        return json.loads(row["data_json"]) if row else None

    def list(self, table: str, tenant_id: str, *, limit: int = 100) -> list[dict]:
        self._validate(table, tenant_id)
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._lock:
            rows = self._connection.execute(
                f'SELECT data_json FROM "{table}" WHERE tenant_id=? '
                "ORDER BY updated_at DESC LIMIT ?", (tenant_id, limit)).fetchall()
        return [json.loads(row["data_json"]) for row in rows]

    def delete(self, table: str, tenant_id: str, record_id: str) -> bool:
        self._validate(table, tenant_id)
        with self.transaction() as connection:
            cursor = connection.execute(
                f'DELETE FROM "{table}" WHERE tenant_id=? AND record_id=?',
                (tenant_id, record_id))
        return cursor.rowcount == 1

    def delete_tenant(self, tenant_id: str) -> int:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        deleted = 0
        with self.transaction() as connection:
            for table in TABLES:
                cursor = connection.execute(
                    f'DELETE FROM "{table}" WHERE tenant_id=?', (tenant_id,))
                deleted += cursor.rowcount
        return deleted

    def consume_once(self, table: str, tenant_id: str, record_id: str,
                     value: dict) -> bool:
        """Atomically consume an issued single-use record if all claims match."""
        self._validate(table, tenant_id)
        now = time.time()
        with self.transaction() as connection:
            row = connection.execute(
                f'SELECT data_json FROM "{table}" WHERE tenant_id=? AND record_id=?',
                (tenant_id, record_id)).fetchone()
            if row is None:
                return False
            payload = json.loads(row["data_json"])
            if (payload.get("status") != "ISSUED"
                    or payload.get("expires_at", 0) < now
                    or any(payload.get(key) != expected for key, expected in value.items()
                           if key != "status")):
                return False
            payload["status"] = "CONSUMED"
            payload["consumed_at"] = now
            cursor = connection.execute(
                f'UPDATE "{table}" SET data_json=?, updated_at=? '
                "WHERE tenant_id=? AND record_id=?",
                (json.dumps(payload, separators=(",", ":")), now, tenant_id, record_id))
        return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()


storage = PlatformStorage()
