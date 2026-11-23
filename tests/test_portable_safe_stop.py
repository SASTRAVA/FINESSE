import json
import sqlite3

import pytest

from scripts.portable_safe_stop import (_active_jobs, checkpoint_and_backup,
                                        create_portable_bundle)


def _job_store(path, *statuses):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs (tenant_id TEXT, record_id TEXT, data_json TEXT, "
            "created_at REAL, updated_at REAL, PRIMARY KEY (tenant_id, record_id))")
        for index, status in enumerate(statuses):
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, 0, 0)",
                ("default", str(index), json.dumps({"status": status})))


def test_active_job_guard_counts_only_in_progress_work(tmp_path):
    database = tmp_path / "platform.db"
    _job_store(database, "queued", "running", "retrying", "complete", "failed")
    assert _active_jobs(database) == 3
    assert _active_jobs(tmp_path / "missing.db") == 0


def test_checkpoint_makes_integrity_checked_backup_and_refuses_overwrite(tmp_path):
    database = tmp_path / "platform.db"
    backup = tmp_path / "backup" / "platform.db"
    _job_store(database, "complete")

    checkpoint_and_backup(database, backup)

    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        checkpoint_and_backup(database, backup)


def test_portable_bundle_contains_hash_manifest_and_qdrant_vault_data(tmp_path):
    backup = tmp_path / "backups" / "platform.db"
    backup.parent.mkdir()
    _job_store(backup, "complete")
    qdrant = tmp_path / "data" / "qdrant"
    qdrant.mkdir(parents=True)
    (qdrant / "vectors.bin").write_bytes(b"synthetic-vector-store")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("synthetic note", encoding="utf-8")
    bundle = create_portable_bundle(backup, qdrant_dir=qdrant, vault_dir=vault)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["files"]} == {
        "platform.db", "qdrant/vectors.bin", "vault.tar.gz"}
    with pytest.raises(FileExistsError):
        create_portable_bundle(backup, qdrant_dir=qdrant, vault_dir=vault)
