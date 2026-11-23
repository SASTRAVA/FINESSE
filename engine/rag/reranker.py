"""Small, deterministic, zero-egress reranker for a bounded RAG candidate set."""
from __future__ import annotations

class LocalReranker:
    """Re-rank at most 25 already-authorized candidates without network calls."""

    def __init__(self, *, candidate_limit: int = 25, score_floor: float = 0.0):
        if not 1 <= candidate_limit <= 25 or score_floor < 0:
            raise ValueError("reranker candidates must be 1..25 and score floor non-negative")
        self.candidate_limit = candidate_limit
        self.score_floor = score_floor

    def rerank(self, query: str, candidates: list[dict], *, limit: int = 8) -> list[dict]:
        bounded = candidates[:self.candidate_limit]
        if not bounded:
            return []
        from .retriever import _bm25_scores
        scores = _bm25_scores(query, [str(item["payload"].get("text", ""))
                                     for item in bounded])
        ranked = []
        for item, score in zip(bounded, scores):
            if score < self.score_floor:
                continue
            ranked.append({**item, "rerank_score": score})
        ranked.sort(key=lambda item: (item["rerank_score"], item["score"]), reverse=True)
        return ranked[:limit]


local_reranker = LocalReranker()
