from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from engine.auth.security import make_token
from engine.config import cfg
from engine.db.storage import PlatformStorage
from engine.main import app
from engine.security.ws_tickets import consume_ticket, issue_ticket


class WebSocketTicketTests(unittest.TestCase):
    def test_ticket_is_opaque_single_use_and_never_stored_in_plaintext(self):
        with TemporaryDirectory() as directory:
            repository = PlatformStorage(str(Path(directory) / "tickets.db"))
            principal = {"sub": "exec@example.test", "role": "COO", "tier": 3,
                         "tenant_id": "default"}
            ticket = issue_ticket(principal, repository)
            self.assertEqual(len(ticket), 43)
            self.assertEqual(consume_ticket(ticket, repository=repository)["sub"], principal["sub"])
            self.assertIsNone(consume_ticket(ticket, repository=repository))
            row = repository._connection.execute(
                "SELECT data_json FROM ws_tickets").fetchone()
            self.assertNotIn(ticket, row[0])
            repository.close()

    def test_ticket_consume_is_atomic_across_threads(self):
        with TemporaryDirectory() as directory:
            repository = PlatformStorage(str(Path(directory) / "tickets.db"))
            ticket = issue_ticket({"sub": "ceo", "role": "CEO", "tier": 4}, repository)
            barrier = threading.Barrier(8)

            def consume():
                barrier.wait()
                return consume_ticket(ticket, repository=repository)

            with ThreadPoolExecutor(max_workers=8) as pool:
                outcomes = list(pool.map(lambda _: consume(), range(8)))
            self.assertEqual(sum(outcome is not None for outcome in outcomes), 1)
            repository.close()

    def test_ws_route_rejects_disallowed_origin_before_accepting(self):
        with TestClient(app) as client:
            token = make_token("ceo", "CEO", 4, "default", amr=("pwd", "mfa"))
            response = client.post("/api/ws-ticket", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 200)
            with self.assertRaises(WebSocketDisconnect) as error:
                with client.websocket_connect(
                    f"/ws?ticket={response.json()['ticket']}",
                    headers={"Origin": "https://attacker.example"},
                ) as socket:
                    socket.receive_json()
            self.assertEqual(error.exception.code, 4403)

    def test_ws_route_consumes_ticket_and_rejects_replay(self):
        with TestClient(app) as client:
            token = make_token("ceo", "CEO", 4, "default", amr=("pwd", "mfa"))
            response = client.post("/api/ws-ticket", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(response.status_code, 200)
            ticket = response.json()["ticket"]
            origin = cfg.CORS_ORIGINS[0]
            with client.websocket_connect(f"/ws?ticket={ticket}", headers={"Origin": origin}) as socket:
                self.assertIsInstance(socket.receive_json(), dict)
                socket.close()
            with self.assertRaises(WebSocketDisconnect) as error:
                with client.websocket_connect(
                    f"/ws?ticket={ticket}", headers={"Origin": origin}
                ) as socket:
                    socket.receive_json()
            self.assertEqual(error.exception.code, 4401)


if __name__ == "__main__":
    unittest.main()
