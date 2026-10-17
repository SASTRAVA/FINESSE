"""
Shared, continuously-evolving memory — the "collective consciousness".

Two coupled surfaces:
  1. Vector memory (semantic) — every result/pattern is embedded back into the
     SAME shared brain the agents retrieve from. So what one swarm learns,
     the next swarm can find. This is the "learns together" mechanism.
  2. Vault memory (human-readable) — patterns are appended to
     vault/13_AI_Memory/Shared_Consciousness.md with a confidence score, so you
     can watch the org's mind evolve inside Obsidian's graph.

Confidence lifecycle (from your Harness Method docs):
  discover 0.60 -> validate 0.75 -> synthesize 0.90 -> adopt 0.95+
Repeated corroboration of a pattern raises its confidence.
"""
from __future__ import annotations
import time
import re
from pathlib import Path

from ..config import cfg
from ..rag.store import store
from .events import bus

_MEM_NOTE = cfg.VAULT / "13_AI_Memory" / "Shared_Consciousness.md"


class SharedMemory:
    async def remember(self, *, text: str, kind: str, role: str, actor: str,
                       trace: str = "", confidence: float = 0.6) -> None:
        """Write a learned pattern / result into the shared brain + vault."""
        await store.upsert(
            [text],
            [{"title": f"{kind}:{role}", "role": "shared", "source": "memory",
              "kind": kind, "actor": actor, "confidence": confidence, "ts": time.time()}],
        )
        await bus.emit("memory", actor, f"wrote {kind} to shared memory (conf {confidence:.2f})",
                       trace=trace)
        self._append_vault(kind, role, actor, text, confidence)

    async def learn_pattern(self, *, pattern: str, role: str, actor: str, trace: str = "") -> float:
        """
        Corroboration-based learning: if a similar pattern already exists, raise
        confidence; else seed at 0.6. Returns the resulting confidence.
        """
        similar = await store.search(pattern, limit=3, flt={"source": "memory"})
        prior = max((p.get("confidence", 0.0) for _, p in similar
                     if p.get("kind") == "pattern"), default=0.0)
        conf = min(0.99, prior + 0.15) if prior else 0.6
        await self.remember(text=pattern, kind="pattern", role=role, actor=actor,
                            trace=trace, confidence=conf)
        if conf >= 0.9:
            await bus.emit("learn", actor, f"pattern reached {conf:.2f} — adopted org-wide",
                           trace=trace)
        return conf

    def _append_vault(self, kind: str, role: str, actor: str, text: str, conf: float) -> None:
        try:
            _MEM_NOTE.parent.mkdir(parents=True, exist_ok=True)
            if not _MEM_NOTE.exists():
                _MEM_NOTE.write_text(
                    "---\ntitle: Shared Consciousness\ntags: [memory, shared, evolving]\n---\n\n"
                    "# Shared Consciousness\n\nThe continuously-evolving collective memory of "
                    "the Sastrava orchestra. Each entry is a pattern or result an agent "
                    "contributed, with a confidence that rises as it is corroborated.\n\n",
                    encoding="utf-8")
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            snippet = re.sub(r"\s+", " ", text).strip()[:400]
            entry = (f"- **[{stamp}] {kind}** · role=`{role}` · by `{actor}` · "
                     f"confidence **{conf:.2f}**\n  > {snippet}\n")
            with _MEM_NOTE.open("a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:  # noqa: BLE001
            print(f"[memory] vault append failed: {e}")


shared_memory = SharedMemory()
