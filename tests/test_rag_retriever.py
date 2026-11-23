from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from engine.rag.retriever import Retriever, _bm25_scores
from engine.rag.reranker import LocalReranker


class HybridRetrieverTests(unittest.TestCase):
    def test_bm25_prioritizes_exact_identifiers(self):
        scores = _bm25_scores("invoice INV-92821", [
            "General billing operations and account management",
            "Invoice INV-92821 is due on Friday",
            "Invoice INV-12000 was already paid",
        ])
        self.assertGreater(scores[1], scores[0])
        self.assertGreater(scores[1], scores[2])

    def test_local_reranker_is_bounded_and_prioritizes_exact_identifiers(self):
        candidates = [
            {"score": 0.9, "payload": {"text": "General account operations"}},
            {"score": 0.1, "payload": {"text": "Invoice INV-92821 due Friday"}},
        ]
        ranked = LocalReranker(candidate_limit=2).rerank("invoice INV-92821", candidates)
        self.assertIn("INV-92821", ranked[0]["payload"]["text"])
        self.assertLessEqual(len(ranked), 8)

    def test_retrieval_always_scopes_tenant_and_returns_citation_references(self):
        hits = [
            (0.98, {"text": "General billing document", "title": "Billing",
                    "source": "vault", "lane": "general", "sensitivity": "internal",
                    "tenant_id": "tenant-a", "document_id": "doc-b", "version": 2}),
            (0.93, {"text": "Invoice INV-92821 due Friday", "title": "Invoice 92821",
                    "source": "vault", "lane": "general", "sensitivity": "internal",
                    "tenant_id": "tenant-a", "document_id": "doc-a", "version": 1}),
            (0.99, {"text": "Invoice INV-92821 from tenant B", "title": "foreign",
                    "source": "vault", "lane": "general", "sensitivity": "internal",
                    "tenant_id": "tenant-b", "document_id": "doc-x", "version": 1}),
        ]
        with patch("engine.rag.retriever.store.search", new=AsyncMock(return_value=hits)) as search:
            result = asyncio.run(Retriever().context_details(
                "invoice INV-92821", role="Analyst", user_id="analyst",
                tenant_id="tenant-a", limit=3))
        self.assertEqual(search.await_args.kwargs["tenant_id"], "tenant-a")
        self.assertEqual(search.await_args.kwargs["flt"]["sensitivity_allowed"],
                         ["public", "internal"])
        self.assertTrue(search.await_args.kwargs["flt"]["is_active"])
        self.assertEqual(search.await_args.kwargs["flt"]["acl_principal_ids"], ["analyst"])
        self.assertEqual(len(result["citations"]), 2)
        self.assertIn("[C1]", result["text"])
        self.assertNotIn("tenant B", result["text"])
        self.assertEqual({citation["doc_id"] for citation in result["citations"]},
                         {"doc-a", "doc-b"})


if __name__ == "__main__":
    unittest.main()
