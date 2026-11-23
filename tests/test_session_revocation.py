from fastapi.testclient import TestClient

from engine.auth.security import decode_token, make_token
from engine.main import app


def test_logout_revokes_token_for_following_requests():
    token = make_token("logout-test@example.invalid", "Software Engineer", 1,
                       "logout-test-tenant")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/me", headers=headers).status_code == 200
    response = client.post("/api/logout", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"logged_out": True}
    assert client.get("/api/me", headers=headers).status_code == 401
    assert decode_token(token) is None
