# P08 handoff: LLMOps, resilience, and FinOps

## Implemented

- Immutable semantic-versioned prompts, tenant overrides, activation/rollback, and 15 checked-in JSON-compatible YAML prompt fixtures.
- Async process-local circuit breaker primitives and sensitivity-aware pool selection. Internal traffic can fall back across configured providers; confidential/restricted selection returns local only and fails closed when no local backend exists.
- Bounded Pydantic v2 JSON validation helper with at most two repair calls.
- Agentic-loop compaction that keeps recent turns, observed citation IDs, approval references, and the maximum sensitivity seen.
- Exact cache keys are wired into low-temperature `LLM.chat` calls and bound to tenant, lane, sensitivity, model, prompt version, and ACL hash. Restricted data and mutating/tool requests bypass it.
- Atomic Redis Lua token reservations when Redis is configured, process-local reservations otherwise; LLM and agentic calls write tenant-scoped usage rows. Agent loop is hard-capped at 12 iterations.
- 25-case synthetic evaluation dataset and deterministic CI smoke checks.

## Remaining P08 gates

- Circuit state is process-local, not shared by Redis across replicas.
- `SemanticCache` currently provides exact-match local caching and an injected backend contract; RedisVL/vector similarity and local embedding integration are not installed.
- The built-in prompt fixtures cover the 15 current registry specs; all 9 prompt-architecture agent identities and planner/synthesizer schema migrations still need reconciliation against the source prompt set.
- Usage tokens are estimated from characters, provider price tables are not configured, and reservation settlement is not a durable distributed reconciliation transaction. USD fields therefore remain zero estimates.
- The CI evaluation is deterministic and mock-judge only. RAGAS Faithfulness, Context Recall, Answer Relevancy, and live release/nightly thresholds are not claimed.
- Live Redis, NVIDIA/Groq/local model availability, cross-replica breaker behavior, and model quality were not exercised in this environment.

## Verification

- `python -m pytest tests/test_llmops_p08.py tests/evals -q`: 8 passed.
- `python -m ruff check --select E4,E7,E9,F --ignore E741 ...`: passed for P08 modules/tests.
- `python -m compileall -q engine tests/test_llmops_p08.py tests/evals`: passed.
- Runtime OpenAPI route inventory contains 164 HTTP operations; storage table count is 50 and RLS migration coverage is checked by the production contract suite.
