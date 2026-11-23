from fastapi.testclient import TestClient
import secrets

from engine.auth.security import decode_token, make_token
from engine.main import app


def scim_credentials(client, tenant_id):
    admin = make_token("scim-admin@example.test", "CEO", 4, tenant_id,
                       amr=("pwd", "mfa"))
    response = client.post("/api/v1/admin/scim/tokens",
                           headers={"Authorization": f"Bearer {admin}"},
                           json={"name": "directory-test"})
    assert response.status_code == 201
    return response.json()["token"]


def test_scim_tenant_scope_create_filter_patch_and_session_revocation():
    client = TestClient(app)
    suffix = secrets.token_hex(4)
    tenant = "scim-lifecycle-" + suffix
    email = f"member-{suffix}@example.test"
    token = scim_credentials(client, tenant)
    headers = {"Authorization": f"Bearer {token}"}

    created = client.post("/scim/v2/Users", headers=headers, json={
        "userName": email, "displayName": "Directory Member",
        "groups": [{"display": "Software Engineer"}],
    })
    assert created.status_code == 201
    assert created.json()["groups"][0]["display"] == "Software Engineer"

    filtered = client.get("/scim/v2/Users",
                          params={"filter": f'userName eq "{email}"'},
                          headers=headers)
    assert filtered.status_code == 200
    assert filtered.json()["totalResults"] == 1

    app_token = make_token(email, "Software Engineer", 1, tenant)
    assert decode_token(app_token) is not None
    changed = client.patch(f"/scim/v2/Users/{email}", headers=headers,
                           json={"Operations": [{"op": "replace", "path": "active",
                                                 "value": False}]})
    assert changed.status_code == 200
    assert changed.json()["active"] is False
    assert decode_token(app_token) is None

    login = client.post("/api/login", json={"email": email,
                                             "password": "unused-random-password",
                                             "tenant_id": tenant})
    assert login.status_code == 401


def test_scim_tokens_cannot_read_or_mutate_another_tenant():
    client = TestClient(app)
    suffix = secrets.token_hex(4)
    tenant = "scim-tenant-a-" + suffix
    email = f"isolated-{suffix}@example.test"
    token = scim_credentials(client, tenant)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/scim/v2/Users", headers=headers, json={
        "userName": email, "displayName": "Tenant A",
    })
    assert created.status_code == 201
    from engine.auth.users import users
    assert users.get(email, tenant) is not None
    assert users.get(email, "scim-tenant-b") is None
    assert client.get(f"/scim/v2/Users/{email}",
                      headers={"Authorization": "Bearer " + "x" * 60}).status_code == 401
