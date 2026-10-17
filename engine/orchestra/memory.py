"""Identity- and lane-scoped semantic memory stored in the vector collection."""
from __future__ import annotations
import time
from ..auth.rbac import role_of
from ..rag.store import store
from .events import bus


class SharedMemory:
    async def remember(self, *, text: str, kind: str, role: str, actor: str,
                       trace: str = "", confidence: float = 0.6,
                       user_id: str = "", lane: str = "", tainted: bool = False,
                       sensitivity: str = "", tenant_id: str = "default") -> None:
        """Persist a private memory scoped to one identity and its current lane."""
        owner = user_id or actor
        memory_lane = lane or role_of(role).lane
        order = ("public", "internal", "confidential", "restricted")
        minimum = "confidential" if memory_lane == "exec" else "internal"
        sensitivity = max((minimum, sensitivity or minimum), key=order.index)
        await store.upsert(
            [text],
            [{"title": f"{kind}:{memory_lane}", "role": memory_lane, "lane": memory_lane,
              "sensitivity": sensitivity, "source": "memory", "owner": owner,
              "tenant_id": tenant_id,
              "kind": kind, "actor": actor, "confidence": confidence, "tainted": tainted,
              "ts": time.time()}],
        )
        await bus.emit("memory", actor, f"wrote private {kind} memory (conf {confidence:.2f})",
                       trace=trace)

    async def learn_pattern(self, *, pattern: str, role: str, actor: str,
                            trace: str = "", user_id: str = "", lane: str = "",
                            tainted: bool = False, sensitivity: str = "",
                            tenant_id: str = "default") -> float:
        """
        Corroboration-based learning: if a similar pattern already exists, raise
        confidence; else seed at 0.6. Returns the resulting confidence.
        """
        if tainted:
            raise ValueError("tainted workflow patterns cannot be learned")
        owner = user_id or actor
        memory_lane = lane or role_of(role).lane
        similar = await store.search(
            pattern, limit=3, flt={"source": "memory", "owner": owner, "lane": memory_lane,
                                  "tenant_id": tenant_id})
        prior = max((p.get("confidence", 0.0) for _, p in similar
                     if p.get("kind") == "pattern"), default=0.0)
        conf = ({0.0: 0.6, 0.6: 0.75, 0.75: 0.9, 0.9: 0.95}.get(
            round(prior, 2), min(0.99, prior + 0.05)) if prior else 0.6)
        await self.remember(text=pattern, kind="pattern", role=role, actor=actor,
                            trace=trace, confidence=conf, user_id=owner, lane=memory_lane,
                            tainted=tainted, sensitivity=sensitivity, tenant_id=tenant_id)
        if conf >= 0.9:
            from ..mcp.base import register_learned_macro
            register_learned_macro(pattern=pattern, tenant_id=tenant_id, owner_sub=owner,
                                   lane=memory_lane, sensitivity=sensitivity or "internal",
                                   requires_approval=memory_lane in {"exec", "security"})
            await bus.emit("learn", actor, f"private pattern reached {conf:.2f} confidence",
                           trace=trace)
        return conf


shared_memory = SharedMemory()
