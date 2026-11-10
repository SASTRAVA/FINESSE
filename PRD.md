# SASTRAVA / FINESSE Product Requirements Document

## 1. Document Control & Executive Summary

| Field | Value |
|---|---|
| Product | SASTRAVA / FINESSE |
| Document | Product Requirements Document |
| Revision | 2.1 — implementation-aligned |
| Status | Active; deployment readiness depends on production service provisioning and CI results |
| Updated | 2026-11-10 |
| Runtime | Python 3.12+, FastAPI, React 18 + TypeScript + Vite |

FINESSE is an AI-assisted operator platform with tenant-scoped workspaces, consulting workflows, agent orchestration, retrieval, CRM/sales capabilities, security review workflows, and web interfaces. External effects remain disabled by default or require explicit authorization. The application is a foundation and does not claim a completed regulated SaaS service: production operation requires PostgreSQL 16, Redis 7 when multi-worker state is needed, external Qdrant for durable vector storage, secret provisioning, monitoring, backups, and an operational review.

## 2. User Personas, Operational Lanes & Four-Tier RBAC

| Persona | Tier | Operational scope |
|---|---:|---|
| CEO | 4 | Tenant administration, emergency controls, executive oversight, approvals |
| COO | 3 | Operational queue, services, campaigns, delivery and approvals |
| Security Auditor / Lead | 3 | Authorized assessment plans, evidence review, security tool certification |
| BizDev & Revenue Lead | 2 | CRM, lead and campaign planning, consent-aware outreach preparation |
| Consulting & Delivery Specialist | 2 | Service intake, Listen → Shape → Deliver workflows, client deliverables |
| Engineering & Analytics Operator | 1 | Assigned engineering, analytics and read-only operational work |

Role definitions in `engine/auth/rbac.py` are authoritative. JWT claims carry tenant scope; each data operation must retain the authenticated tenant and permitted lane. Administrative tiers do not imply consent to external data transfer or live outreach. High-impact tools, scanning and provider actions require the explicit approval and policy gates implemented by their route/provider contracts.

## 3. Core Functional Requirements (FR-1 through FR-5)

| ID | Requirement | Implementation boundary |
|---|---|---|
| FR-1 | Authenticate users, enforce role/tier access, and isolate tenant records. | JWT auth, RBAC, tenant-aware storage, PostgreSQL RLS in production. |
| FR-2 | Provide reviewable agent and consulting workflows across the SASTRAVA service lines. | Orchestrator, review-only conjunction graphs, service catalog and intake. No automatic external side effects from planning. |
| FR-3 | Provide retrieval and memory with tenant, lane, sensitivity and owner metadata. | Qdrant/local development backend; remote cluster requires `QDRANT_URL` and optional API key. |
| FR-4 | Support CRM, email, voice, calendar and sales operations with safe defaults. | Dry-run default; provider live flags, tenant consent/suppression and single-use human authorization required. |
| FR-5 | Provide authorized security planning, evidence management and operational observability. | Scanner registry defaults to no auto-execution; certification gates are evidence-driven; telemetry is opt-in. |

## 4. Complete End-to-End API Specification

The table below is generated from the live FastAPI router registry in this repository. It lists each registered application HTTP method/path binding after excluding FastAPI's four generated documentation routes. Repeated method/path decorators are retained because they are separate route bindings. The current runtime contract contains 134 bindings (including a duplicated sales route registration); this does not equal 134 unique URL paths. The generated OpenAPI schema at `/openapi.json` is the canonical request, response, parameter, status-code and security-schema contract. `GET /api/health` is the setup diagnostic; `/health` is the lightweight liveness response.

| Method | Path | Registered in |
|---|---|---|
| `POST` | `/api/login` | `engine.main` |
| `POST` | `/api/auth/change-password` | `engine.main` |
| `GET` | `/api/me` | `engine.main` |
| `POST` | `/api/users` | `engine.main` |
| `GET` | `/api/users` | `engine.main` |
| `GET` | `/api/roles` | `engine.main` |
| `POST` | `/api/inject/text` | `engine.main` |
| `POST` | `/api/inject/file` | `engine.main` |
| `POST` | `/api/directive` | `engine.main` |
| `POST` | `/api/agent/run` | `engine.main` |
| `POST` | `/api/voice` | `engine.main` |
| `POST` | `/api/tts` | `engine.main` |
| `GET` | `/api/swarms` | `engine.main` |
| `GET` | `/api/hermes` | `engine.main` |
| `POST` | `/api/security/audit` | `engine.main` |
| `GET` | `/api/security/report` | `engine.main` |
| `GET` | `/api/graph` | `engine.main` |
| `GET` | `/api/agents` | `engine.main` |
| `GET` | `/api/manifest` | `engine.main` |
| `GET` | `/api/tools` | `engine.main` |
| `POST` | `/api/tools/call` | `engine.main` |
| `POST` | `/api/agents/new` | `engine.main` |
| `GET` | `/api/crm/pipeline` | `engine.main` |
| `POST` | `/api/crm/leads` | `engine.main` |
| `POST` | `/api/crm/generate` | `engine.main` |
| `GET` | `/api/sastrava/catalog` | `engine.main` |
| `POST` | `/api/sastrava/intake` | `engine.main` |
| `POST` | `/api/sastrava/security-scope` | `engine.main` |
| `POST` | `/api/sastrava/learning-plan` | `engine.main` |
| `POST` | `/api/crm/leads/{lead_id}/stage` | `engine.main` |
| `POST` | `/api/crm/leads/{lead_id}/approve-outreach` | `engine.main` |
| `POST` | `/api/reweave` | `engine.main` |
| `GET` | `/api/status` | `engine.main` |
| `GET` | `/` | `engine.main` |
| `GET` | `/universe` | `engine.main` |
| `GET` | `/dashboard` | `engine.main` |
| `GET` | `/innovation` | `engine.main` |
| `POST` | `/api/diagram` | `engine.main` |
| `GET` | `/api/innovation` | `engine.main` |
| `GET` | `/voice` | `engine.main` |
| `GET` | `/jarvis` | `engine.main` |
| `GET` | `/command` | `engine.main` |
| `GET` | `/api/audit` | `engine.main` |
| `GET` | `/api/command/overview` | `engine.main` |
| `GET` | `/api/keys` | `engine.main` |
| `GET` | `/health` | `engine.main` |
| `GET` | `/api/health` | `engine.main` |
| `GET` | `/api/v1/platform/runtime` | `engine.main` |
| `POST` | `/hubapi/token` | `engine.hub_api` |
| `GET` | `/hubapi/swarm/clusters` | `engine.hub_api` |
| `POST` | `/hubapi/problems` | `engine.hub_api` |
| `GET` | `/hubapi/gatekeeper/queue` | `engine.hub_api` |
| `GET` | `/api/v1/services` | `engine.sales.router_v1` |
| `POST` | `/api/v1/auth/login` | `engine.sales.router_v1` |
| `POST` | `/api/v1/auth/refresh` | `engine.sales.router_v1` |
| `POST` | `/api/v1/auth/logout` | `engine.sales.router_v1` |
| `GET` | `/api/v1/users/me` | `engine.sales.router_v1` |
| `GET` | `/api/v1/services/{service_id}` | `engine.sales.router_v1` |
| `GET` | `/api/v1/icps` | `engine.sales.router_v1` |
| `POST` | `/api/v1/agent/commands` | `engine.sales.router_v1` |
| `POST` | `/api/v1/orchestra/conjunction` | `engine.sales.router_v1` |
| `POST` | `/api/v1/memory/patterns` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/generate` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns/plan` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns` | `engine.sales.router_v1` |
| `GET` | `/api/v1/campaigns` | `engine.sales.router_v1` |
| `GET` | `/api/v1/campaigns/{campaign_id}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns/{campaign_id}/approve` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns/{campaign_id}/pause` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns/{campaign_id}/resume` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns/{campaign_id}/cancel` | `engine.sales.router_v1` |
| `POST` | `/api/v1/campaigns/{campaign_id}/match-services` | `engine.sales.router_v1` |
| `GET` | `/api/v1/leads` | `engine.sales.router_v1` |
| `GET` | `/api/v1/leads/search` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/bulk-import` | `engine.sales.router_v1` |
| `GET` | `/api/v1/leads/export` | `engine.sales.router_v1` |
| `GET` | `/api/v1/leads/{lead_id}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/{lead_id}/enrich` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/{lead_id}/verify` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/{lead_id}/score` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/{lead_id}/approve` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/generate` | `engine.sales.router_v1` |
| `GET` | `/api/v1/email/templates` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/generate-batch` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/campaigns/{campaign_id}/start` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/unsubscribe` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/email/events` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/preview` | `engine.sales.router_v1` |
| `GET` | `/api/v1/email/messages` | `engine.sales.router_v1` |
| `GET` | `/api/v1/email/messages/{message_id}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/email/replies` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/send` | `engine.sales.router_v1` |
| `POST` | `/api/v1/voice/calls` | `engine.sales.router_v1` |
| `POST` | `/api/v1/voice/commands` | `engine.sales.router_v1` |
| `POST` | `/api/v1/voice/campaigns/{campaign_id}/start` | `engine.sales.router_v1` |
| `GET` | `/api/v1/voice/calls/{call_id}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/voice/calls/{call_id}/hangup` | `engine.sales.router_v1` |
| `POST` | `/api/v1/voice/calls/{call_id}/transfer` | `engine.sales.router_v1` |
| `POST` | `/api/v1/voice/calls/{call_id}/summarize` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/voice/events` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/voice/transcripts` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/voice/recordings` | `engine.sales.router_v1` |
| `GET` | `/api/v1/voice/sessions` | `engine.sales.router_v1` |
| `GET` | `/api/v1/analytics/funnel` | `engine.sales.router_v1` |
| `GET` | `/api/v1/analytics/overview` | `engine.sales.router_v1` |
| `GET` | `/api/v1/analytics/campaigns/{campaign_id}` | `engine.sales.router_v1` |
| `GET` | `/api/v1/audit-logs` | `engine.sales.router_v1` |
| `GET` | `/api/v1/jobs/dlq` | `engine.sales.router_v1` |
| `GET` | `/api/v1/jobs/{job_id}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | `engine.sales.router_v1` |
| `GET` | `/api/v1/calendar/slots` | `engine.sales.router_v1` |
| `GET` | `/api/v1/calendar/meetings` | `engine.sales.router_v1` |
| `POST` | `/api/v1/email/unsubscribe/{token}` | `engine.sales.router_v1` |
| `GET` | `/api/v1/email/unsubscribe/{token}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/calendar/meetings` | `engine.sales.router_v1` |
| `POST` | `/api/v1/leads/{lead_id}/enrich` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/providers/email` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/providers/voice` | `engine.sales.router_v1` |
| `POST` | `/api/v1/webhooks/providers/voice/opt-out` | `engine.sales.router_v1` |
| `PUT` | `/api/v1/settings/provider-secrets` | `engine.sales.router_v1` |
| `DELETE` | `/api/v1/settings/provider-secrets/{name}` | `engine.sales.router_v1` |
| `POST` | `/api/v1/compliance/check` | `engine.sales.router_v1` |
| `GET` | `/api/v1/suppression-list` | `engine.sales.router_v1` |
| `GET` | `/api/v1/catalog/repositories` | `engine.sales.router_v1` |
| `POST` | `/api/v1/catalog/repositories/certify` | `engine.sales.router_v1` |
| `GET` | `/api/v1/memory/patterns` | `engine.sales.router_v1` |
| `POST` | `/api/v1/security/verify-target` | `engine.sales.router_v1` |
| `POST` | `/api/v1/security/scans` | `engine.sales.router_v1` |
| `GET` | `/api/v1/security/tools` | `engine.sales.router_v1` |
| `POST` | `/api/v1/admin/emergency-stop` | `engine.sales.router_v1` |
| `POST` | `/api/v1/privacy/consent` | `engine.sales.router_v1` |
| `DELETE` | `/api/v1/privacy/tenant-data` | `engine.sales.router_v1` |
| `POST` | `/api/admin/emergency-stop` | `engine.main` |
| `DELETE` | `/api/sastrava/scans/{scan_id}/evidence` | `engine.main` |

Authentication, role checks, request models, response models and status codes remain defined on the individual FastAPI endpoints. WebSocket contracts are `/ws` (authenticated live event stream) and `/hubapi/gatekeeper/stream` (tier-3+ queue snapshots authenticated by token). The route inventory is verified by `finesse_e2e_production_tests.py` and OpenAPI can be inspected locally with `python -c "from engine.main import app; print(app.openapi())"`.

## 5. Non-Functional, Security & Data Isolation Requirements (NFR-01 through NFR-06)

| ID | Requirement |
|---|---|
| NFR-01 — Tenant isolation | PostgreSQL 16 production tables must have both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`; application role must be `NOSUPERUSER NOBYPASSRLS`; each request transaction binds tenant scope with a parameterized `set_config`. |
| NFR-02 — Safe startup | `ENVIRONMENT=production` requires PostgreSQL. Production startup must not silently select SQLite or `/tmp`; health reports missing production configuration. SQLite remains a local/test option. |
| NFR-03 — Secret protection | Provider secrets use tenant-bound AES-GCM envelopes. New envelopes record a key ID (`kid`); previous key material remains available during staged rotation. Secrets are never committed or embedded in docs. |
| NFR-04 — Outbound safety | Confidential/restricted egress is blocked unless explicitly allowed; recognized secrets and PII are scrubbed; public fetches reject private, loopback and link-local destinations. |
| NFR-05 — Human control | Sales and security actions are opt-in, bounded and reviewable; Gatekeeper approval tokens are action-bound, tenant-bound, short-lived and single-use. Redis is used for shared nonce state when configured. |
| NFR-06 — Deployment and resilience | Frontend build and Python verification run in CI. PostgreSQL/Redis/Qdrant and OpenTelemetry are explicit service/configuration dependencies; local in-memory/SQLite paths are for local/test use only. Production requires backups, restore drills, monitoring and load/security testing. |

## 6. Production Transformation Roadmap (Phases 1–3)

| Phase | Scope | Completion evidence |
|---|---|---|
| 1 — Stateful core | PostgreSQL 16 schema migration, role/RLS verification, production fail-closed persistence, migration ledger. | Startup applies pending migrations and verifies all tenant tables and role attributes; deployment operator provisions PostgreSQL and runs smoke checks. |
| 2 — Distributed runtime | Redis 7 shared Gatekeeper nonce state and WebSocket fan-out; Qdrant cluster with API key and payload indexes. | Redis-backed nonce is atomically consumed once; streams broadcast across workers; Qdrant indexes tenant/lane/sensitivity. External services must be provisioned and reachable. |
| 3 — Delivery and observability | CI quality/security pipeline, `kid`-versioned KMS envelope rotation, opt-in OpenTelemetry HTTP/graph/job spans. | CI checks pass; key rotation retains old keys until records/backups are re-encrypted/expired; OTLP export works when enabled. |

These implementation changes do not provision external services or create production credentials. Do not mark a phase operationally complete until its external dependencies, deployment environment and recovery process have been verified.

## 7. Verification & Test Suite Matrix

| Verification | Scope | Execution |
|---|---|---|
| Existing automated suite | Unit, API, security, provider, Vercel, and platform tests under `tests/` (measured baseline: 101 unittest cases; pytest discovers these unittest cases). | `python -m pytest tests/ -v` |
| 15 production contract suites | Routes; 24-table RLS; tenant SQL binding; 8-thread idempotency; KMS; SSRF; prompt/egress; auth/proxy; Gatekeeper; webhook signatures; ICS; RAG scope; review graph/memory; scanner/certification; container hardening. | `python finesse_e2e_production_tests.py` |
| Frontend build | React/TypeScript operator workspace. | `cd frontend && npm ci && npm run build` |
| Static/security tools | Ruff, focused mypy checks, pip-audit and Trivy filesystem vulnerability/secret scanning. | `.github/workflows/ci.yml` |
| Production service checks | Live PostgreSQL 16 role/RLS, Redis 7 nonce/pubsub, remote Qdrant indexes, Vercel environment and API/UI smoke checks. | Follow `DEPLOY_TO_VERCEL.md`; tests that require credentials/services are not represented as passing by local unit tests. |
