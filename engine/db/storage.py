"""Tenant-keyed persistence using SQLite locally or PostgreSQL with transaction RLS."""
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
    "tenant_secrets",
)


class PlatformStorage:
    """JSON-record repository with SQLite fallback or PostgreSQL transaction RLS."""

    def __init__(self, path: str | None = None):
        self._lock = threading.RLock()
        self._is_postgres = path is None and cfg.DATABASE_URL.startswith(
            ("postgres://", "postgresql://"))
        if self._is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("install psycopg[binary] to enable PostgreSQL RLS storage") from exc
            self._connection = psycopg.connect(
                cfg.DATABASE_URL, autocommit=True, row_factory=dict_row)
        else:
            database = path or str(cfg.DATA / "platform.db")
            self._connection = sqlite3.connect(database, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            for table in TABLES:
                self._execute(
                    f'CREATE TABLE IF NOT EXISTS "{table}" ('
                    "tenant_id TEXT NOT NULL, record_id TEXT NOT NULL, "
                    f"data_json {'JSONB' if self._is_postgres else 'TEXT'} NOT NULL, "
                    f"created_at {'DOUBLE PRECISION' if self._is_postgres else 'REAL'} NOT NULL, "
                    f"updated_at {'DOUBLE PRECISION' if self._is_postgres else 'REAL'} NOT NULL, "
                    "PRIMARY KEY (tenant_id, record_id))")
                self._execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_tenant" '
                              f'ON "{table}" (tenant_id)')
                if self._is_postgres:
                    self._execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
                    self._execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
                    self._execute(f'DROP POLICY IF EXISTS tenant_isolation_policy ON "{table}"')
                    self._execute(
                        f'CREATE POLICY tenant_isolation_policy ON "{table}" USING '
                        "(tenant_id::text = current_setting('app.current_tenant_id', true)) "
                        "WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))")
            if not self._is_postgres:
                self._connection.commit()

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self._is_postgres else statement

    def _execute(self, statement: str, parameters: tuple = ()):
        return self._connection.execute(self._sql(statement), parameters)

    def _decode(self, value):
        return json.loads(value) if isinstance(value, str) else value

    @staticmethod
    def _validate(table: str, tenant_id: str) -> None:
        if table not in TABLES:
            raise ValueError("unknown platform table")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")

    @contextmanager
    def transaction(self, tenant_id: str | None = None) -> Iterator[object]:
        with self._lock:
            if self._is_postgres and (not tenant_id or not tenant_id.strip()):
                raise ValueError("tenant_id is required for a PostgreSQL transaction")
            try:
                if self._is_postgres:
                    with self._connection.transaction():
                        self._execute(
                            "SELECT set_config('app.current_tenant_id', ?, true)", (tenant_id,))
                        yield self._connection
                else:
                    yield self._connection
                    self._connection.commit()
            except Exception:
                if not self._is_postgres:
                    self._connection.rollback()
                raise

    def put(self, table: str, tenant_id: str, record_id: str, value: dict) -> dict:
        self._validate(table, tenant_id)
        if not record_id:
            raise ValueError("record_id is required")
        now = time.time()
        payload = dict(value)
        payload["tenant_id"] = tenant_id
        insert = (
            f'INSERT INTO "{table}" (tenant_id, record_id, data_json, created_at, updated_at) '
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(tenant_id, record_id) DO UPDATE SET "
            "data_json=excluded.data_json, updated_at=excluded.updated_at")
        if self._is_postgres:
            insert = insert.replace("VALUES (?, ?, ?, ?, ?)",
                                    "VALUES (?, ?, ?::jsonb, ?, ?)")
        with self.transaction(tenant_id) as connection:
            connection.execute(self._sql(insert),
                (tenant_id, record_id, json.dumps(payload, separators=(",", ":")), now, now))
        return payload

    def get(self, table: str, tenant_id: str, record_id: str) -> dict | None:
        self._validate(table, tenant_id)
        with self.transaction(tenant_id) as connection:
            row = connection.execute(self._sql(
                f'SELECT data_json FROM "{table}" WHERE tenant_id=? AND record_id=?'),
                (tenant_id, record_id)).fetchone()
        return self._decode(row["data_json"]) if row else None

    def list(self, table: str, tenant_id: str, *, limit: int = 100) -> list[dict]:
        self._validate(table, tenant_id)
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.transaction(tenant_id) as connection:
            rows = connection.execute(self._sql(
                f'SELECT data_json FROM "{table}" WHERE tenant_id=? '
                "ORDER BY updated_at DESC LIMIT ?"), (tenant_id, limit)).fetchall()
        return [self._decode(row["data_json"]) for row in rows]

    def delete(self, table: str, tenant_id: str, record_id: str) -> bool:
        self._validate(table, tenant_id)
        with self.transaction(tenant_id) as connection:
            cursor = connection.execute(self._sql(
                f'DELETE FROM "{table}" WHERE tenant_id=? AND record_id=?'),
                (tenant_id, record_id))
        return cursor.rowcount == 1

    def put_if_absent(self, table: str, tenant_id: str, record_id: str,
                      value: dict) -> bool:
        """Atomically create a tenant-scoped record; never overwrite an existing key."""
        self._validate(table, tenant_id)
        if not record_id:
            raise ValueError("record_id is required")
        now = time.time()
        payload = dict(value)
        payload["tenant_id"] = tenant_id
        insert = (f'INSERT INTO "{table}" (tenant_id, record_id, data_json, created_at, updated_at) '
                  "VALUES (?, ?, ?, ?, ?) ON CONFLICT(tenant_id, record_id) DO NOTHING")
        if self._is_postgres:
            insert = insert.replace("VALUES (?, ?, ?, ?, ?)",
                                    "VALUES (?, ?, ?::jsonb, ?, ?)")
        else:
            insert = insert.replace("INSERT INTO", "INSERT OR IGNORE INTO").replace(
                " ON CONFLICT(tenant_id, record_id) DO NOTHING", "")
        with self.transaction(tenant_id) as connection:
            cursor = connection.execute(self._sql(insert),
                                        (tenant_id, record_id,
                                         json.dumps(payload, separators=(",", ":")), now, now))
        return cursor.rowcount == 1

    def delete_tenant(self, tenant_id: str) -> int:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        deleted = 0
        with self.transaction(tenant_id) as connection:
            for table in TABLES:
                cursor = connection.execute(self._sql(
                    f'DELETE FROM "{table}" WHERE tenant_id=?'), (tenant_id,))
                deleted += cursor.rowcount
        return deleted

    def consume_once(self, table: str, tenant_id: str, record_id: str,
                     value: dict) -> bool:
        """Atomically consume an issued single-use record if all claims match."""
        self._validate(table, tenant_id)
        now = time.time()
        with self.transaction(tenant_id) as connection:
            query = f'SELECT data_json FROM "{table}" WHERE tenant_id=? AND record_id=?'
            if self._is_postgres:
                query += " FOR UPDATE"
            row = connection.execute(self._sql(query),
                (tenant_id, record_id)).fetchone()
            if row is None:
                return False
            payload = self._decode(row["data_json"])
            if (payload.get("status") != "ISSUED"
                    or payload.get("expires_at", 0) < now
                    or any(payload.get(key) != expected for key, expected in value.items()
                           if key != "status")):
                return False
            payload["status"] = "CONSUMED"
            payload["consumed_at"] = now
            update = (f'UPDATE "{table}" SET data_json=?, updated_at=? '
                      "WHERE tenant_id=? AND record_id=?")
            if self._is_postgres:
                update = update.replace("data_json=?", "data_json=?::jsonb")
            cursor = connection.execute(self._sql(update),
                (json.dumps(payload, separators=(",", ":")), now, tenant_id, record_id))
        return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()


storage = PlatformStorage()
