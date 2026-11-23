from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from engine.audit.pg_audit import HashChainedAuditLog
from engine.db.storage import PlatformStorage


class HashChainedAuditTests(unittest.TestCase):
    def test_chain_is_tenant_scoped_append_only_and_verifiable(self):
        with TemporaryDirectory() as directory:
            repository = PlatformStorage(str(Path(directory) / "audit.db"))
            audit = HashChainedAuditLog(repository)
            first = audit.append("tenant-a", {"action": "login", "actor": "person-a"})
            second = audit.append("tenant-a", {"action": "password_changed", "actor": "person-a"})
            audit.append("tenant-b", {"action": "login", "actor": "person-b"})

            self.assertEqual(second["previous_hash"], first["event_hash"])
            self.assertTrue(audit.verify("tenant-a"))
            self.assertTrue(audit.verify("tenant-b"))
            rows = repository._connection.execute(
                "SELECT * FROM audit_events WHERE tenant_id='tenant-a'").fetchall()
            self.assertEqual(len(rows), 2)
            with self.assertRaisesRegex(Exception, "append-only"):
                repository._connection.execute(
                    "UPDATE audit_events SET event_hash='tampered' WHERE tenant_id='tenant-a'")
            with self.assertRaisesRegex(Exception, "append-only"):
                repository._connection.execute(
                    "DELETE FROM audit_events WHERE tenant_id='tenant-a'")
            repository.close()


if __name__ == "__main__":
    unittest.main()
