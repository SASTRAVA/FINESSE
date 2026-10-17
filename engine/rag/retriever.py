"""
Retriever — hybrid retrieval + context assembly.

Combines dense vector search (semantic) with a cheap keyword/BM25-ish overlap
score (lexical), then assembles a compact context block. Lane-scoped requests
search only that lane plus explicitly shared/global documents.
"""
from __future__ import annotations
import re
from typing import List, Optional

from ..auth.rbac import max_sensitivity, permitted_lanes
from ..prompt_guard import is_untrusted_source, wrap_untrusted_content
from .store import store


def _lexical(query: str, text: str) -> float:
    q = set(re.findall(r"\w+", query.lower()))
    d = set(re.findall(r"\w+", text.lower()))
    if not q or not d:
        return 0.0
    return len(q & d) / len(q)


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
        raw = []
        for allowed_lane in lanes:
            raw.extend(await store.search(
                query, limit=limit * 3,
                flt={"lane": allowed_lane, "tenant_id": tenant_id}))

        results = []
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
            lex = _lexical(query, text)
            hybrid = 0.75 * float(score) + 0.25 * lex
            results.append({"score": hybrid, "payload": payload,
                            "tainted": bool(payload.get("tainted"))
                            or is_untrusted_source(payload.get("source", ""))})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

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
        blocks, total = [], 0
        sensitivity_order = ("public", "internal", "confidential", "restricted")
        sensitivity = "public"
        tainted = False
        for h in hits:
            p = h["payload"]
            snippet = p.get("text", "").strip()
            head = f"[{p.get('title','?')} · {p.get('source','?')} · score={h['score']:.2f}]"
            tainted = tainted or h["tainted"]
            if sensitivity_order.index(p["sensitivity"]) > sensitivity_order.index(sensitivity):
                sensitivity = p["sensitivity"]
            snippet = wrap_untrusted_content(snippet, p.get("source", "external"))
            block = f"{head}\n{snippet}"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
        return {"text": "\n\n---\n\n".join(blocks) if blocks else "(no relevant brain context found)",
                "sensitivity": sensitivity, "tainted": tainted}


retriever = Retriever()
