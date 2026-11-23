"""Stop the portable Compose stack and checkpoint/back up its SQLite store."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess
import tarfile

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


def create_portable_bundle(backup: Path, *, qdrant_dir: Path | None = None,
                           vault_dir: Path | None = None) -> Path:
    """Bundle stopped-service SQLite, local Qdrant files, and vault with hashes."""
    bundle = backup.with_suffix("").with_name(backup.stem + "-bundle")
    staging = bundle.with_name(bundle.name + ".staging")
    if bundle.exists() or staging.exists():
        raise FileExistsError("refusing to overwrite an existing portable backup bundle")
    staging.mkdir(parents=True)
    try:
        import shutil
        sqlite_snapshot = staging / "platform.db"
        shutil.copy2(backup, sqlite_snapshot)
        artifacts: list[Path] = [sqlite_snapshot]
        if qdrant_dir and qdrant_dir.is_dir():
            target = staging / "qdrant"
            shutil.copytree(qdrant_dir, target)
            artifacts.extend(path for path in target.rglob("*") if path.is_file())
        if vault_dir and vault_dir.is_dir():
            vault_archive = staging / "vault.tar.gz"
            with tarfile.open(vault_archive, "w:gz") as archive:
                for path in vault_dir.rglob("*"):
                    if path.is_file():
                        archive.add(path, arcname=path.relative_to(vault_dir))
            artifacts.append(vault_archive)
        file_entries = []
        for path in artifacts:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            file_entries.append({
                "path": path.relative_to(staging).as_posix() if path.is_relative_to(staging)
                else path.name,
                "sha256": digest.hexdigest(), "size_bytes": path.stat().st_size})
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": file_entries,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.replace(bundle)
        return bundle
    except Exception:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.portable")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "portable-runtime" / "data")
    parser.add_argument("--vault-dir", type=Path, default=ROOT / "portable-runtime" / "vault")
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
    bundle = create_portable_bundle(
        backup, qdrant_dir=args.data_dir.resolve() / "qdrant",
        vault_dir=args.vault_dir.resolve())
    print(f"portable stack stopped; SQLite checkpoint and integrity-checked backup: {backup}")
    print(f"portable Qdrant/vault backup bundle: {bundle}")
    print("Wait for containers to stop completely before safely ejecting the SSD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
