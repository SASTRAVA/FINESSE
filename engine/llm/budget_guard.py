"""Atomic token reservations backed by Redis Lua; local mode is explicitly process-local."""
from __future__ import annotations

import time
import uuid

from ..db.storage import storage

_RESERVE = """
local tenant = tonumber(redis.call('GET', KEYS[1]) or '0')
local user = tonumber(redis.call('GET', KEYS[2]) or '0')
local amount = tonumber(ARGV[1])
if tenant + amount > tonumber(ARGV[2]) then return 0 end
if user + amount > tonumber(ARGV[3]) then return -1 end
redis.call('INCRBY', KEYS[1], amount); redis.call('INCRBY', KEYS[2], amount)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4])); redis.call('EXPIRE', KEYS[2], tonumber(ARGV[5]))
return 1
"""


class BudgetExceeded(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class BudgetGuard:
    def __init__(self, redis_client=None, repository=storage):
        self.redis, self.repository = redis_client, repository
        self._local: dict[str, int] = {}
        self._reservations: dict[str, tuple[str, str, int]] = {}

    def reserve(self, *, tenant_id: str, user_id: str, amount: int,
                tenant_limit: int, user_daily_limit: int) -> str:
        if amount < 1 or tenant_limit < 1 or user_daily_limit < 1:
            raise ValueError("token reservation and limits must be positive")
        now = time.gmtime()
        month = time.strftime("%Y%m", now)
        day = time.strftime("%Y%m%d", now)
        tkey, ukey = f"finesse:budget:{tenant_id}:{month}", f"finesse:user:{tenant_id}:{user_id}:{day}"
        if self.redis is not None:
            result = int(self.redis.eval(_RESERVE, 2, tkey, ukey, amount, tenant_limit,
                                         user_daily_limit, 40 * 86400, 2 * 86400))
            if result == 0:
                raise BudgetExceeded("TENANT_BUDGET_EXCEEDED")
            if result < 0:
                raise BudgetExceeded("USER_QUOTA_EXCEEDED")
        else:
            current = self._local.get(tkey, 0)
            user_current = self._local.get(ukey, 0)
            if current + amount > tenant_limit:
                raise BudgetExceeded("TENANT_BUDGET_EXCEEDED")
            if user_current + amount > user_daily_limit:
                raise BudgetExceeded("USER_QUOTA_EXCEEDED")
            self._local[tkey], self._local[ukey] = current + amount, user_current + amount
        reservation_id = uuid.uuid4().hex
        self._reservations[reservation_id] = (tkey, ukey, amount)
        return reservation_id

    def settle(self, reservation_id: str, actual_tokens: int) -> None:
        reservation = self._reservations.pop(reservation_id, None)
        if reservation is None:
            return
        tkey, ukey, reserved = reservation
        actual = min(reserved, max(0, actual_tokens))
        refund = reserved - actual
        if refund:
            if self.redis is not None:
                self.redis.decrby(tkey, refund)
                self.redis.decrby(ukey, refund)
            else:
                self._local[tkey] = max(0, self._local.get(tkey, 0) - refund)
                self._local[ukey] = max(0, self._local.get(ukey, 0) - refund)

    def record(self, *, reservation_id: str, tenant_id: str, user_id: str,
               agent_id: str, provider: str, model: str, prompt_version: str,
               sensitivity: str, input_tokens: int, output_tokens: int,
               estimated_cost_usd: float = 0.0, cached_tokens: int = 0,
               cache_hit: bool = False, latency_ms: int = 0) -> None:
        record = {"user_id": user_id, "agent_id": agent_id, "provider": provider,
                  "model": model, "prompt_version": prompt_version,
                  "sensitivity": sensitivity, "input_tokens": input_tokens,
                  "output_tokens": output_tokens, "cached_tokens": cached_tokens,
                  "estimated_cost_usd": max(0.0, estimated_cost_usd),
                  "cache_hit": cache_hit, "latency_ms": max(0, latency_ms),
                  "created_at": time.time()}
        self.repository.put("llm_usage_ledger", tenant_id, reservation_id, record)


budget_guard = BudgetGuard()
