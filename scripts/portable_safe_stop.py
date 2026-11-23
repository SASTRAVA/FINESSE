"""Stop the portable Compose stack and checkpoint/back up its SQLite store."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def _active_jobs(database: Path) -> int:
    if not database.exists():
        return 0
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if table is None:
            return 0
        rows = connection.execute("SELECT data_json FROM jobs").fetchall()
    import json
    return sum(json.loads(row[0]).get("status") in {"queued", "running", "retrying"}
               for row in rows)


def checkpoint_and_backup(database: Path, backup: Path) -> None:
    if not database.exists():
        raise FileNotFoundError(f"SQLite database not found: {database}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise FileExistsError("refusing to overwrite an existing backup")
    with sqlite3.connect(database, timeout=30) as source:
        checkpoint = source.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and checkpoint[0] != 0:
            raise RuntimeError("SQLite WAL checkpoint is busy; backup was not created")
        with sqlite3.connect(backup) as target:
            source.backup(target)
            check = target.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError("SQLite backup integrity check failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.portable")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "portable-runtime" / "data")
    parser.add_argument("--compose-file", type=Path, default=ROOT / "deploy" / "compose.portable.yaml")
    parser.add_argument("--wait-seconds", type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 1800:
        parser.error("--wait-seconds must be between 1 and 1800")
    if not args.env_file.is_file() or not args.compose_file.is_file():
        parser.error("portable env file and Compose file must exist")

    database = args.data_dir.resolve() / "platform.db"
    active = _active_jobs(database)
    if active:
        raise SystemExit(f"refusing to stop: {active} queued or running job(s) remain")

    command = ["docker", "compose", "--env-file", str(args.env_file.resolve()),
               "-f", str(args.compose_file.resolve()), "stop", "--timeout",
               str(args.wait_seconds)]
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        return result.returncode

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = args.data_dir.resolve().parent / "backups" / f"platform-{stamp}.db"
    checkpoint_and_backup(database, backup)
    print(f"portable stack stopped; SQLite checkpoint and integrity-checked backup: {backup}")
    print("Wait for containers to stop completely before safely ejecting the SSD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
