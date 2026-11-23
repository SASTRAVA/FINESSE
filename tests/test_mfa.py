from __future__ import annotations

import base64
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from engine.db.storage import PlatformStorage
from engine.db.tenant_secrets import TenantSecretStore
from engine.security.mfa import MFAService, _counter_code


class MFAServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.repository = PlatformStorage(str(Path(self.temp_dir.name) / "mfa.db"))
        self.secret_store = TenantSecretStore(
            self.repository, master_key="MFA-test-only-master-key-material-2026",
            active_key_id="test-v1", keyring={})
        self.mfa = MFAService(self.repository, self.secret_store)

    def tearDown(self):
        self.repository.close()
        self.temp_dir.cleanup()

    @staticmethod
    def code_for(secret_b32: str, now: float) -> str:
        secret = base64.b32decode(secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8))
        return _counter_code(secret, int(now // 30))

    def test_enrollment_encrypts_seed_and_returns_single_use_recovery_codes(self):
        now = time.time()
        email = "exec@example.test"
        setup = self.mfa.begin_enrollment("tenant-a", email)
        secret_record = self.repository.get("tenant_secrets", "tenant-a",
                                            f"mfa-totp:{email}")
        factor_before = self.repository.get("user_mfa_factors", "tenant-a", email)
        self.assertNotIn(setup["secret"], str(secret_record))
        self.assertEqual(factor_before["recovery_hashes"], [])
        self.assertIn("algorithm=SHA1&digits=6&period=30", setup["provisioning_uri"])

        recovery_codes = self.mfa.complete_enrollment(
            "tenant-a", email, self.code_for(setup["secret"], now), now=now)

        self.assertEqual(len(recovery_codes), 8)
        factor = self.repository.get("user_mfa_factors", "tenant-a", email)
        self.assertTrue(factor["enabled"])
        self.assertEqual(len(factor["recovery_hashes"]), 8)
        self.assertNotIn(recovery_codes[0], str(factor))
        self.assertTrue(self.mfa.status("tenant-a", email)["enrolled"])

    def test_totp_replay_is_rejected_and_recovery_code_is_single_use(self):
        now = int(time.time() // 30) * 30 + 1
        email = "coo@example.test"
        setup = self.mfa.begin_enrollment("tenant-a", email)
        first_code = self.code_for(setup["secret"], now)
        recovery_codes = self.mfa.complete_enrollment(
            "tenant-a", email, first_code, now=now)

        next_time = now + 30
        next_code = self.code_for(setup["secret"], next_time)
        self.assertTrue(self.mfa.verify("tenant-a", email, next_code, now=next_time))
        self.assertFalse(self.mfa.verify("tenant-a", email, next_code, now=next_time))
        self.assertTrue(self.mfa.verify("tenant-a", email, recovery_codes[0]))
        self.assertFalse(self.mfa.verify("tenant-a", email, recovery_codes[0]))
        self.assertFalse(self.mfa.verify("tenant-b", email, recovery_codes[1]))

    def test_enrollment_requires_valid_code_and_expires(self):
        email = "admin@example.test"
        setup = self.mfa.begin_enrollment("tenant-a", email)
        with self.assertRaisesRegex(ValueError, "invalid MFA code"):
            self.mfa.complete_enrollment("tenant-a", email, "000000")
        current = time.time()
        code = self.code_for(setup["secret"], current + 601)
        with self.assertRaisesRegex(ValueError, "no longer valid"):
            self.mfa.complete_enrollment("tenant-a", email, code, now=current + 601)

    def test_duplicate_enabled_enrollment_is_refused_and_disable_requires_factor(self):
        now = time.time()
        email = "owner@example.test"
        setup = self.mfa.begin_enrollment("tenant-a", email)
        codes = self.mfa.complete_enrollment(
            "tenant-a", email, self.code_for(setup["secret"], now), now=now)
        with self.assertRaisesRegex(ValueError, "already enrolled"):
            self.mfa.begin_enrollment("tenant-a", email)

        code = self.code_for(setup["secret"], now + 30)
        self.assertTrue(self.mfa.disable("tenant-a", email, code, now=now + 30))
        self.assertFalse(self.mfa.status("tenant-a", email)["enrolled"])
        self.assertIsNone(self.secret_store.get("tenant-a", f"mfa-totp:{email}"))
        self.assertEqual(len(codes), 8)


if __name__ == "__main__":
    unittest.main()
