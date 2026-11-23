# P15 handoff: scale and adversarial validation

- Added a deterministic red-team regression suite for indirect prompt injection, confidential egress, citation fabrication, MCP manifest drift, cache tenant isolation, and token budget exhaustion. These are local code-level tests, not model red-team benchmarks.
- Added a k6 35-VU health/readiness smoke script with p95/p99 and error-rate thresholds. It deliberately does not invoke billable LLMs or mutate CRM data.
- No k6 load run, multi-replica load stack, chaos drill, or third-party penetration test was executed. Those require k6/Docker and a disposable staging topology with authorized synthetic tenants.
