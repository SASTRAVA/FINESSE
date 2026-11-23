import json
import sqlite3

import pytest

from scripts.portable_safe_stop import _active_jobs, checkpoint_and_backup


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
