"""Small, transaction-safe runner for the repository's PostgreSQL migrations."""
from __future__ import annotations

import re
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def verify_postgres_role(connection) -> None:
    """Reject roles that can bypass row-level security, including superusers."""
    row = connection.execute(
        "SELECT r.rolbypassrls, r.rolsuper FROM pg_roles AS r "
        "WHERE r.rolname = current_user"
    ).fetchone()
    if row is None:
        raise RuntimeError("could not inspect the connected PostgreSQL role")
    bypass = row["rolbypassrls"] if isinstance(row, dict) else row[0]
    superuser = row["rolsuper"] if isinstance(row, dict) else row[1]
    if bypass or superuser:
        raise RuntimeError(
            "PostgreSQL application role must have NOBYPASSRLS and NOSUPERUSER")


def apply_pending_migrations(connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply numbered SQL migrations once, atomically and in lexical order."""
    directory = Path(migrations_dir) if migrations_dir else MIGRATIONS_DIR
    connection.execute(
        "CREATE TABLE IF NOT EXISTS finesse_schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    applied: list[str] = []
    for path in sorted(directory.glob("[0-9][0-9][0-9]_*.sql")):
        version = path.name
        if not re.fullmatch(r"\d{3}_[A-Za-z0-9_.-]+\.sql", version):
            raise RuntimeError(f"invalid migration filename: {version}")
        if connection.execute(
                "SELECT 1 FROM finesse_schema_migrations WHERE version=%s", (version,)
        ).fetchone():
            continue
        sql = path.read_text(encoding="utf-8")
        with connection.transaction():
            # psycopg's simple-query mode accepts the migration's DO block.
            connection.execute(sql, prepare=False)
            connection.execute(
                "INSERT INTO finesse_schema_migrations(version) VALUES (%s)", (version,))
        applied.append(version)
    return applied


def verify_tenant_rls(connection, tables: tuple[str, ...]) -> None:
    """Verify every platform table exists with both RLS flags and a policy."""
    rows = connection.execute(
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND c.relname = ANY(%s)", (list(tables),)
    ).fetchall()
    found = {
        (row["relname"] if isinstance(row, dict) else row[0]): (
            row["relrowsecurity"] if isinstance(row, dict) else row[1],
            row["relforcerowsecurity"] if isinstance(row, dict) else row[2],
        )
        for row in rows
    }
    missing = set(tables) - found.keys()
    if missing:
        raise RuntimeError("PostgreSQL tenant tables missing after migrations: "
                           + ", ".join(sorted(missing)))
    weak = [name for name, flags in found.items() if not all(flags)]
    if weak:
        raise RuntimeError("row-level security is not enabled and forced on: "
                           + ", ".join(sorted(weak)))
    policies = connection.execute(
        "SELECT tablename FROM pg_policies WHERE schemaname=current_schema() "
        "AND policyname='tenant_isolation_policy' AND tablename = ANY(%s)",
        (list(tables),)
    ).fetchall()
    policy_tables = {row["tablename"] if isinstance(row, dict) else row[0]
                     for row in policies}
    if policy_tables != set(tables):
        raise RuntimeError("tenant_isolation_policy is missing from one or more tenant tables")
