from __future__ import annotations

import unittest

from scripts.export_openapi import PUBLIC_REASONS, build_inventory


class RouteAuthMatrixTests(unittest.TestCase):
    def test_every_unsecured_http_operation_has_an_exact_reviewed_reason(self):
        inventory = build_inventory()
        unsecured = {(item["method"], item["path"])
                     for item in inventory["http_operations"] if not item["authenticated"]}
        self.assertEqual(unsecured, set(PUBLIC_REASONS))

    def test_all_privileged_websockets_require_single_use_tickets_and_origin_checks(self):
        inventory = build_inventory()
        self.assertEqual({item["path"] for item in inventory["websockets"]},
                         {"/ws", "/hubapi/gatekeeper/stream"})
        for socket in inventory["websockets"]:
            self.assertEqual(socket["authentication"], "opaque single-use ticket")
            self.assertTrue(socket["origin_check"])


if __name__ == "__main__":
    unittest.main()
