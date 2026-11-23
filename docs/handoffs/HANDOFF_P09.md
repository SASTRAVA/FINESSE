# P09 handoff: SRE, observability, and disaster recovery

## Implemented

- `engine/observability/logging.py` formats selected correlation fields as JSON and redacts secret/PII keys and recognized credential/email values before output.
- `engine/observability/metrics.py` records low-cardinality HTTP counts and bounded Prometheus duration histograms. `/metrics` requires `read:all`, a configured `METRICS_TOKEN`, and a private or loopback source address.
- `/healthz` is a simple liveness probe. `/readyz` is 503 before startup readiness and after shutdown begins.
- `engine/llm/concurrency_guard.py` provides cancellation-aware priority admission for local inference; provider calls use it with an environment-configured process-local cap.
- Existing optional OTLP HTTP trace setup remains available.

## Remaining P09 gates

- Circuit state, local inference semaphore, and metrics are process-local; horizontal replicas do not share these counters/limits. Redis coordination and leak recovery need a live Redis service.
- There is no full OpenTelemetry instrumentation of Redis, Qdrant, database, or worker jobs, nor a validated Langfuse/Phoenix deployment.
- Metrics provide bounded HTTP histograms, but not GPU exporters, SIEM streaming, alert rules, or the Grafana dashboard specified in P09.
- Graceful shutdown does not yet drain WebSockets/ARQ workers or flush/close all external pools.
- Alembic is not installed/configured. Existing ordered SQL migrations do not yet have the expand/backfill/switch/contract linter.
- PostgreSQL PITR and Qdrant snapshot restore drills require disposable live service instances and backup storage; no destructive restore drill was run.

## Verification

- P09 primitives have deterministic local tests for redaction, metric cardinality, and priority/concurrency behavior.
- Full pytest, route inventory, production contracts, migrations, frontend, and security scans are tracked by the construction verification report after all prompt modules.
