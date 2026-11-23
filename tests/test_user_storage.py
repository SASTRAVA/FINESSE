from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.auth.users import UserStore
from engine.db.storage import PlatformStorage


class TenantUserStorageTests(unittest.TestCase):
    def test_database_backed_users_are_tenant_scoped_and_store_only_password_hashes(self):
        with TemporaryDirectory() as directory:
            repository = PlatformStorage(str(Path(directory) / "users.db"))
            users = UserStore(repository=repository)
            password = "Tenant-user-test-password-2026"
            users.create("person@example.test", "Tenant Person", "Analyst", password,
                         tenant_id="tenant-a")

            self.assertIsNone(users.get("person@example.test", "tenant-b"))
            self.assertIsNone(users.authenticate("person@example.test", password,
                                                 "tenant-b"))
            authenticated = users.authenticate("person@example.test", password,
                                               "tenant-a")
            self.assertEqual(authenticated.tenant_id, "tenant-a")
            self.assertEqual(len(users.all_public("tenant-a")), 1)
            persisted = repository.get("users", "tenant-a", "person@example.test")
            self.assertNotIn(password, str(persisted))
            self.assertTrue(persisted["pw_hash"].startswith("$2"))
            self.assertEqual(users.all_public("tenant-b"), [])
            repository.close()

    def test_password_update_writes_only_the_target_tenant_user(self):
        with TemporaryDirectory() as directory:
            repository = PlatformStorage(str(Path(directory) / "users.db"))
            users = UserStore(repository=repository)
            users.create("a@example.test", "Tenant A", "Analyst",
                         "Tenant-a-user-password-2026", tenant_id="tenant-a")
            users.create("b@example.test", "Tenant B", "Analyst",
                         "Tenant-b-user-password-2026", tenant_id="tenant-b")

            with patch.object(repository, "put", wraps=repository.put) as put:
                users.change_password("a@example.test", "Tenant-a-user-password-2026",
                                      "Tenant-a-new-password-2026", tenant_id="tenant-a")

            self.assertEqual(put.call_count, 1)
            self.assertEqual(put.call_args.args[:3],
                             ("users", "tenant-a", "a@example.test"))
            repository.close()


if __name__ == "__main__":
    unittest.main()
