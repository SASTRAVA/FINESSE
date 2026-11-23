"""
Retriever — hybrid retrieval + context assembly.

Combines dense vector search (semantic) with a cheap keyword/BM25-ish overlap
score (lexical), then assembles a compact context block. Lane-scoped requests
search only that lane plus explicitly shared/global documents.
"""
from __future__ import annotations
import math
import re
from typing import List, Optional

from ..auth.rbac import max_sensitivity, permitted_lanes
from ..prompt_guard import is_untrusted_source, wrap_untrusted_content
from .citations import citation_record
from .reranker import local_reranker
from .store import store


def _bm25_scores(query: str, documents: list[str]) -> list[float]:
    """Small in-process BM25 ranker for the bounded candidate set returned by Qdrant."""
    query_terms = re.findall(r"\w+", query.casefold())
    tokenized = [re.findall(r"\w+", text.casefold()) for text in documents]
    if not query_terms or not tokenized:
        return [0.0] * len(documents)
    average_length = sum(map(len, tokenized)) / max(len(tokenized), 1)
    document_frequency = {
        term: sum(term in set(tokens) for tokens in tokenized)
        for term in set(query_terms)
    }
    scores = []
    for tokens in tokenized:
        frequencies: dict[str, int] = {}
        for term in tokens:
            frequencies[term] = frequencies.get(term, 0) + 1
        score = 0.0
        for term in query_terms:
            tf = frequencies.get(term, 0)
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (len(tokenized) - df + 0.5) / (df + 0.5))
            denominator = tf + 1.2 * (1 - 0.75 + 0.75 * len(tokens)
                                       / max(average_length, 1.0))
            score += idf * tf * 2.2 / denominator
        scores.append(score)
    return scores


class Retriever:
    async def retrieve(self, query: str, *, role: Optional[str] = None,
                       lane: Optional[str] = None, user_id: str = "",
                       tenant_id: str = "default", limit: int = 6) -> List[dict]:
        principal = role or lane or "general"
        allowed_lanes = permitted_lanes(principal)
        if lane is not None:
            if lane not in allowed_lanes:
                return []
            lanes = (lane,)
        else:
            lanes = allowed_lanes
        sensitivity_order = ("public", "internal", "confidential", "restricted")
        clearance = sensitivity_order.index(max_sensitivity(principal))
        allowed_sensitivities = list(sensitivity_order[:clearance + 1])
        raw = []
        for allowed_lane in lanes:
            raw.extend(await store.search(
                query, limit=limit * 3,
                flt={"lane": allowed_lane, "tenant_id": tenant_id,
                     "sensitivity_allowed": allowed_sensitivities, "is_active": True,
                     "acl_principal_ids": [user_id] if user_id else []},
                tenant_id=tenant_id))

        candidates = []
        seen = set()
        for score, payload in raw:
            chunk_lane = payload.get("lane")
            sensitivity = payload.get("sensitivity")
            if chunk_lane not in lanes or sensitivity not in sensitivity_order:
                continue
            if payload.get("tenant_id", "default") != tenant_id:
                continue
            if sensitivity_order.index(sensitivity) > clearance:
                continue
            source = payload.get("source")
            owner_scoped = source in {
                "memory", "vault_injected", "prompt", "hub_idea", "pdf", "docx",
                "txt", "md", "csv", "xlsx", "xlsm", "file"}
            owner = payload.get("owner") or payload.get("injected_by")
            if owner_scoped and (not user_id or owner != user_id):
                continue
            text = payload.get("text", "")
            identity = (payload.get("title"), payload.get("path"), payload.get("source"),
                        payload.get("chunk"), payload.get("owner"), text)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append({"dense_score": float(score), "payload": payload,
                               "tainted": bool(payload.get("tainted"))
                               or is_untrusted_source(payload.get("source", ""))})
        dense_order = sorted(range(len(candidates)),
                             key=lambda index: candidates[index]["dense_score"], reverse=True)
        bm25_values = _bm25_scores(
            query, [str(item["payload"].get("text", "")) for item in candidates])
        bm25_order = sorted(range(len(candidates)),
                            key=lambda index: bm25_values[index], reverse=True)
        dense_rank = {index: rank for rank, index in enumerate(dense_order, start=1)}
        bm25_rank = {index: rank for rank, index in enumerate(bm25_order, start=1)}
        results = []
        for index, candidate in enumerate(candidates):
            candidate["score"] = (1 / (60 + dense_rank[index])
                                  + 1 / (60 + bm25_rank[index]))
            candidate["dense_rank"] = dense_rank[index]
            candidate["bm25_rank"] = bm25_rank[index]
            results.append(candidate)
        results.sort(key=lambda result: result["score"], reverse=True)
        return local_reranker.rerank(query, results[:25], limit=limit)

    async def context(self, query: str, *, role: Optional[str] = None,
                      lane: Optional[str] = None, user_id: str = "",
                      tenant_id: str = "default", limit: int = 6,
                      max_chars: int = 4000) -> str:
        return (await self.context_details(query, role=role, lane=lane, user_id=user_id,
                                           tenant_id=tenant_id, limit=limit,
                                           max_chars=max_chars))["text"]

    async def context_details(self, query: str, *, role: Optional[str] = None,
                              lane: Optional[str] = None, user_id: str = "",
                              tenant_id: str = "default", limit: int = 6,
                              max_chars: int = 4000) -> dict:
        hits = await self.retrieve(query, role=role, lane=lane, user_id=user_id,
                                   tenant_id=tenant_id, limit=limit)
        blocks, total, citations = [], 0, []
        sensitivity_order = ("public", "internal", "confidential", "restricted")
        sensitivity = "public"
        tainted = False
        for h in hits:
            p = h["payload"]
            snippet = p.get("text", "").strip()
            citation = f"C{len(citations) + 1}"
            head = (f"[{citation}] {p.get('title','?')} · {p.get('source','?')} "
                    f"· score={h['score']:.4f}")
            tainted = tainted or h["tainted"]
            if sensitivity_order.index(p["sensitivity"]) > sensitivity_order.index(sensitivity):
                sensitivity = p["sensitivity"]
            snippet = wrap_untrusted_content(snippet, p.get("source", "external"))
            block = f"{head}\n{snippet}"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
            citations.append(citation_record(citation, p, snippet).as_dict())
        return {"text": "\n\n---\n\n".join(blocks) if blocks else "(no relevant brain context found)",
                "sensitivity": sensitivity, "tainted": tainted, "citations": citations}


retriever = Retriever()
