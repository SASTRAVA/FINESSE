import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

import engine.main as main
from engine.auth import make_token
from engine.config import cfg
from engine.hub_api import hub_stream, map_idea
from engine.rag.retriever import retriever


class _Socket:
    def __init__(self):
        self.close_code = None

    async def close(self, code):
        self.close_code = code


class SecurityGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_hub_problem_requires_authentication(self):
        response = self.client.post(
            "/hubapi/problems", json={"statement": "A sufficiently detailed idea"}
        )
        self.assertEqual(response.status_code, 401)

    def test_demo_hub_admin_login_is_rejected(self):
        with patch("engine.auth.users.users.authenticate", return_value=None):
            response = self.client.post(
                "/hubapi/token", data={"username": "ADMIN", "password": "0000"}
            )
        self.assertEqual(response.status_code, 401)

    def test_hub_queue_is_restricted_to_executives(self):
        token = make_token("staff@example.com", "Software Engineer", 1)
        response = self.client.get(
            "/hubapi/gatekeeper/queue",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_global_graph_is_restricted_to_executives(self):
        token = make_token("staff@example.com", "Software Engineer", 1)
        response = self.client.get(
            "/api/graph", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 403)

    def test_hub_stream_rejects_non_executive_token(self):
        socket = _Socket()
        token = make_token("staff@example.com", "Software Engineer", 1)
        asyncio.run(hub_stream(socket, token))
        self.assertEqual(socket.close_code, 4403)

    def test_innovation_cannot_run_without_lane_permissions(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(map_idea(
                "A sufficiently detailed idea",
                {"sub": "staff@example.com", "role": "Legal Advisor"},
            ))
        self.assertEqual(raised.exception.status_code, 403)

    def test_retrieval_queries_only_the_calling_lane_and_shared_memory(self):
        searched_roles = []

        async def fake_search(query, limit, flt=None):
            role = flt["role"]
            searched_roles.append(role)
            payload = {"role": role, "title": role, "text": f"context for {role}"}
            return [(0.9, payload)]

        with patch("engine.rag.retriever.store.search", new=AsyncMock(side_effect=fake_search)):
            hits = asyncio.run(retriever.retrieve("project context", role="marketing"))

        self.assertEqual(searched_roles, ["marketing", "shared", "global"])
        self.assertEqual({hit["payload"]["role"] for hit in hits},
                         {"marketing", "shared", "global"})

    def test_upload_filename_cannot_escape_upload_directory(self):
        token = make_token("staff@example.com", "Software Engineer", 1)
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            upload_dir = root / "uploads"
            upload_dir.mkdir()
            outside_file = root / "escape.txt"

            with patch.object(cfg, "UPLOADS", upload_dir), \
                    patch("engine.main.ingest_file",
                          new=AsyncMock(return_value={"chunks": 1})), \
                    patch("engine.main.users.bump"):
                response = self.client.post(
                    "/api/inject/file",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("..\\escape.txt", b"safe", "text/plain")},
                )

            self.assertEqual(response.status_code, 200)
            self.assertFalse(outside_file.exists())
            self.assertEqual(list(upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
