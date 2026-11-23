import asyncio

import pytest
from pydantic import BaseModel

from engine.db.storage import PlatformStorage
from engine.llm.budget_guard import BudgetExceeded, BudgetGuard
from engine.llm.prompt_registry import PromptRegistry
from engine.llm.resilient_router import CircuitBreakers, CircuitOpen, eligible_pool
from engine.llm.semantic_cache import CacheScope, SemanticCache
from engine.llm.structured import StructuredOutputError, generate_structured
from engine.orchestra.compactor import compact


class _Answer(BaseModel):
    answer: str


def test_prompt_registry_immutability_activation_and_rollback():
    store = PlatformStorage(":memory:")
    registry = PromptRegistry(store)
    registry.register("agent", "1.0.0", "v1", tenant_id="tenant")
    registry.register("agent", "2.0.0", "v2", tenant_id="tenant")
    with pytest.raises(ValueError):
        registry.register("agent", "1.0.0", "changed", tenant_id="tenant")
    registry.activate("agent", "2.0.0", tenant_id="tenant")
    assert registry.resolve("agent", tenant_id="tenant").system_prompt == "v2"
    registry.activate("agent", "1.0.0", tenant_id="tenant")
    assert registry.resolve("agent", tenant_id="tenant").version_semver == "1.0.0"
    store.close()


def test_circuit_breaker_and_sensitivity_pools():
    async def _raise():
        raise RuntimeError("synthetic upstream failure")
    async def run():
        breaker = CircuitBreakers(threshold=2, cooldown_s=10)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await breaker.call("nim", _raise)
        with pytest.raises(CircuitOpen):
            await breaker.acquire("nim")
    asyncio.run(run())
    assert eligible_pool("confidential", local_available=False, cloud_available=True) == ()
    assert eligible_pool("confidential", local_available=True, cloud_available=True) == ("local",)


def test_structured_output_bounded_retry_and_error():
    async def run():
        calls = 0
        async def completion(_feedback):
            nonlocal calls
            calls += 1
            return "{bad" if calls == 1 else '{"answer":"ok"}'
        assert (await generate_structured(completion, _Answer)).answer == "ok"
        async def invalid(_feedback):
            return "{}"
        with pytest.raises(StructuredOutputError):
            await generate_structured(invalid, _Answer, max_retries=1)
    asyncio.run(run())


def test_compactor_retains_taint_citations_and_recent_messages():
    messages = [{"role": "user", "content": f"old [C1] approval ID: gate-1234 {i}",
                 "sensitivity": "confidential" if i == 0 else "public"} for i in range(30)]
    result = compact(messages, context_limit=30, trigger_ratio=0.7, preserve_tail=4)
    assert result.compacted and result.sensitivity == "confidential"
    assert "[C1]" in result.messages[0]["content"]
    assert len(result.messages) == 5


def test_semantic_cache_isolates_all_dimensions_and_skips_restricted():
    async def run():
        cache = SemanticCache()
        base = CacheScope("A", "finance", "internal", "m1", "1.0.0", "acl1")
        await cache.set("query", "answer", base)
        assert await cache.get("query", base) == "answer"
        changed_scopes = (
            CacheScope("B", "finance", "internal", "m1", "1.0.0", "acl1"),
            CacheScope("A", "security", "internal", "m1", "1.0.0", "acl1"),
            CacheScope("A", "finance", "confidential", "m1", "1.0.0", "acl1"),
            CacheScope("A", "finance", "internal", "m2", "1.0.0", "acl1"),
            CacheScope("A", "finance", "internal", "m1", "2.0.0", "acl1"),
            CacheScope("A", "finance", "internal", "m1", "1.0.0", "acl2"),
        )
        for changed in changed_scopes:
            assert await cache.get("query", changed) is None
        restricted = CacheScope("A", "finance", "restricted", "m1", "1.0.0", "acl1")
        assert await cache.get("query", restricted) is None
    asyncio.run(run())


def test_budget_guard_enforces_limits_and_records_usage():
    store = PlatformStorage(":memory:")
    guard = BudgetGuard(repository=store)
    reservation = guard.reserve(tenant_id="tenant", user_id="user", amount=10,
                                tenant_limit=20, user_daily_limit=10)
    with pytest.raises(BudgetExceeded, match="USER_QUOTA_EXCEEDED"):
        guard.reserve(tenant_id="tenant", user_id="user", amount=1,
                      tenant_limit=20, user_daily_limit=10)
    guard.record(reservation_id=reservation, tenant_id="tenant", user_id="user",
                 agent_id="agent", provider="local", model="m", prompt_version="1.0.0",
                 sensitivity="internal", input_tokens=5, output_tokens=5)
    assert store.get("llm_usage_ledger", "tenant", reservation)["output_tokens"] == 5
    store.close()
