from __future__ import annotations

import base64
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from engine.auth.users import User
from engine.auth.security import make_token
from engine.db.storage import storage
from engine.main import app
from engine.security.mfa import _counter_code


class MFAAuthenticationFlowTests(unittest.TestCase):
    def test_l4_login_requires_enrollment_then_issues_mfa_bound_session(self):
        email = f"mfa-{uuid.uuid4().hex[:10]}@example.test"
        tenant = f"tenant-mfa-{uuid.uuid4().hex[:10]}"
        principal = User(email=email, name="MFA Executive", role="CEO", tier=4,
                         tenant_id=tenant, pw_hash="not-used-by-test")
        client = TestClient(app)
        with patch("engine.main.users.authenticate", return_value=principal):
            login = client.post("/api/login", json={
                "email": email, "password": "test-password", "tenant_id": tenant})
        self.assertEqual(login.status_code, 200)
        challenge = login.json()
        self.assertTrue(challenge["mfa_required"])
        self.assertTrue(challenge["enrollment_required"])
        self.assertNotIn("token", challenge)

        headers = {"Authorization": "Bearer " + challenge["challenge_token"]}
        blocked = client.get("/api/me", headers=headers)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()["detail"], "MFA_REQUIRED")

        enrollment = client.post("/api/auth/mfa/enroll", headers=headers)
        self.assertEqual(enrollment.status_code, 200, enrollment.text)
        secret = enrollment.json()["secret"]
        now = time.time()
        key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
        code = _counter_code(key, int(now // 30))
        verified = client.post("/api/auth/mfa/verify", headers=headers,
                               json={"code": code})
        self.assertEqual(verified.status_code, 200, verified.text)
        result = verified.json()
        self.assertEqual(len(result["recovery_codes"]), 8)

        session_headers = {"Authorization": "Bearer " + result["access_token"]}
        profile = client.get("/api/me", headers=session_headers)
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["email"], email)
        replay = client.post("/api/auth/mfa/verify", headers=headers,
                            json={"code": code})
        self.assertEqual(replay.status_code, 401)

    def test_password_only_admin_token_is_denied(self):
        token = make_token("legacy-admin@example.test", "CEO", 4)
        response = TestClient(app).get(
            "/api/me", headers={"Authorization": "Bearer " + token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "MFA_REQUIRED")
        headers = {"Authorization": "Bearer " + token}
        sales = TestClient(app).get("/api/v1/services", headers=headers)
        hub = TestClient(app).post("/hubapi/problems", headers=headers,
                                   json={"statement": "A sufficiently detailed test problem"})
        self.assertEqual(sales.status_code, 403)
        self.assertEqual(hub.status_code, 403)

    def test_tenant_can_require_mfa_for_non_executive_roles(self):
        email = f"sales-{uuid.uuid4().hex[:10]}@example.test"
        tenant = f"tenant-policy-{uuid.uuid4().hex[:10]}"
        principal = User(email=email, name="Tenant Sales", role="Sales Manager", tier=2,
                         tenant_id=tenant, pw_hash="not-used-by-test")
        storage.put("tenant_identity_settings", tenant, tenant,
                    {"require_mfa": True, "updated_by": "policy-test"})
        with patch("engine.main.users.authenticate", return_value=principal):
            login = TestClient(app).post("/api/login", json={
                "email": email, "password": "test-password", "tenant_id": tenant})
        self.assertTrue(login.json()["mfa_required"])
        self.assertTrue(login.json()["enrollment_required"])

        password_only = make_token(email, "Sales Manager", 2, tenant, amr=("pwd",))
        response = TestClient(app).get(
            "/api/me", headers={"Authorization": "Bearer " + password_only})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "MFA_REQUIRED")

    def test_all_password_login_surfaces_issue_mfa_challenges_for_l4(self):
        email = f"admin-{uuid.uuid4().hex[:10]}@example.test"
        tenant = f"tenant-surfaces-{uuid.uuid4().hex[:10]}"
        principal = User(email=email, name="MFA Admin", role="CEO", tier=4,
                         tenant_id=tenant, pw_hash="not-used-by-test")
        client = TestClient(app)
        with patch("engine.main.users.authenticate", return_value=principal):
            hub = client.post("/hubapi/token", data={
                "username": email, "password": "test-password", "tenant_id": tenant})
            sales = client.post("/api/v1/auth/login", json={
                "email": email, "password": "test-password", "tenant_id": tenant})
        self.assertEqual(hub.status_code, 200)
        self.assertTrue(hub.json()["mfa_required"])
        self.assertNotIn("access_token", hub.json())
        self.assertEqual(sales.status_code, 200)
        self.assertTrue(sales.json()["mfa_required"])
        self.assertNotIn("access_token", sales.json())

    def test_l4_can_set_tenant_mfa_policy_and_policy_is_enforced_immediately(self):
        tenant = f"tenant-policy-api-{uuid.uuid4().hex[:10]}"
        client = TestClient(app)
        admin = make_token("owner@example.test", "CEO", 4, tenant,
                           amr=("pwd", "mfa"))
        staff = make_token("staff@example.test", "Sales Manager", 2, tenant,
                           amr=("pwd",))
        headers = {"Authorization": "Bearer " + admin}

        enabled = client.put("/api/v1/admin/tenant-security", headers=headers,
                             json={"require_mfa": True})
        self.assertEqual(enabled.status_code, 200, enabled.text)
        denied = client.get("/api/me", headers={"Authorization": "Bearer " + staff})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["detail"], "MFA_REQUIRED")

        disabled = client.put("/api/v1/admin/tenant-security", headers=headers,
                              json={"require_mfa": False})
        self.assertEqual(disabled.status_code, 200, disabled.text)
        allowed = client.get("/api/me", headers={"Authorization": "Bearer " + staff})
        self.assertEqual(allowed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
