"""
Retriever — hybrid retrieval + context assembly.

Combines dense vector search (semantic) with a cheap keyword/BM25-ish overlap
score (lexical), then assembles a compact context block. Lane-scoped requests
search only that lane plus explicitly shared/global documents.
"""
from __future__ import annotations
import re
from typing import List, Optional

from .store import store


def _lexical(query: str, text: str) -> float:
    q = set(re.findall(r"\w+", query.lower()))
    d = set(re.findall(r"\w+", text.lower()))
    if not q or not d:
        return 0.0
    return len(q & d) / len(q)


class Retriever:
    async def retrieve(self, query: str, *, role: Optional[str] = None,
                       limit: int = 6) -> List[dict]:
        # Role-scoped searches query only that lane and explicitly shared material.
        roles = tuple(dict.fromkeys((role, "shared", "global"))) if role is not None else ()
        if roles:
            raw = []
            for allowed_role in roles:
                raw.extend(await store.search(query, limit=limit * 3,
                                              flt={"role": allowed_role}))
        else:
            raw = await store.search(query, limit=limit * 3)

        results = []
        seen = set()
        for score, payload in raw:
            text = payload.get("text", "")
            identity = (payload.get("title"), payload.get("path"), payload.get("source"),
                        payload.get("chunk"), text)
            if identity in seen:
                continue
            seen.add(identity)
            lex = _lexical(query, text)
            hybrid = 0.75 * float(score) + 0.25 * lex
            results.append({"score": hybrid, "payload": payload})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    async def context(self, query: str, *, role: Optional[str] = None,
                      limit: int = 6, max_chars: int = 4000) -> str:
        hits = await self.retrieve(query, role=role, limit=limit)
        blocks, total = [], 0
        for h in hits:
            p = h["payload"]
            snippet = p.get("text", "").strip()
            head = f"[{p.get('title','?')} · {p.get('source','?')} · score={h['score']:.2f}]"
            block = f"{head}\n{snippet}"
            if total + len(block) > max_chars:
                break
            blocks.append(block)
            total += len(block)
        return "\n\n---\n\n".join(blocks) if blocks else "(no relevant brain context found)"


retriever = Retriever()
