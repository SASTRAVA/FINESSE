# FINESSE codebase index

## Runtime map

1. `engine/config.py` loads environment settings and resolves portable data paths.
2. `engine/main.py` mounts authentication, operator APIs, health checks, and the browser event stream; `engine/hub_api.py` mounts the Innovation Hub; `engine/sales/router_v1.py` mounts the tenant-scoped sales and platform API.
3. `engine/auth/` defines roles, token validation, password hashing, and user storage. PostgreSQL mode persists users through tenant RLS; development and portable modes use the local JSON store.
4. `engine/db/storage.py` is the tenant-keyed persistence boundary. PostgreSQL transactions bind `app.current_tenant_id`; local mode uses SQLite WAL with full synchronous commits. `migrations/` holds ordered PostgreSQL RLS changes.
5. `engine/rag/` validates uploads, chunks/embeds documents, stores vectors in Qdrant, and retrieves by tenant, lane, sensitivity, and owner. `engine/llm/` applies provider selection, egress blocking, and scrubbing.
6. `engine/orchestra/`, `engine/agents/`, and `engine/mcp/` handle planning, jobs, tools, and review gates. External effects default to dry-run or explicit authorization.
7. `frontend/` builds the React operator workspace to `engine/web/react-ui/`; `engine/web/` also contains legacy operator pages and the built Innovation Hub client.
8. `deploy/` contains production and portable Compose profiles. Hardware encryption and bootable-OS behavior are external to this application.

## Dependency order and playbook status

| Prompt | Area | Repository status at baseline of this construction |
| --- | --- | --- |
| P00 | Governance, source map, CI, secret hygiene | Existing CI; source map and route inventory added during this work. No repo-specific license decision supplied. |
| P01 | Security audit and threat model | Existing security controls and contract probes; consolidated audit baseline added during this work. No penetration test performed. |
| P02 | PostgreSQL identity, transaction RLS, route auth | PostgreSQL-backed tenant user persistence and route inventory added; live PostgreSQL pool stress is still a service test. |
| P03 | Qdrant isolation, egress and Gatekeeper binding | Existing tenant filters, sensitivity checks, redaction, and approval bindings; full live cluster tests require service provisioning. |
| P04 | Redis sessions, WebSocket auth, audit chain | Opaque single-use WebSocket tickets, origin checks, and append-only hash-chained security audit storage added; JWT session revocation and live Redis fan-out validation remain. |
| P05 | Async bounded ingestion and vault adapters | Upload signatures and archive-expansion bounds added; durable worker handoff and S3 adapter remain. |
| P06 | SSO, MFA, SCIM, signing-key rotation | Not implemented; requires IdP configuration and provisioning policy. |
| P07 | Versioned hybrid RAG, citations, ACL connectors | Tenant-scoped lexical+dense retrieval exists; lifecycle/versioning and connector sync remain. |
| P08 | Prompt registry, provider resilience, budgets, evals | Retry, cache, and egress controls exist; prompt registry, tenant budgets, and evaluation harness remain. |
| P09 | Observability, concurrency, DR | Optional OTLP and local bounds exist; live dashboards, backup restore drills, and migration framework remain. |
| P10 | Gatekeeper channels, MCP OAuth, webhooks | Existing signed inbound hooks and tool approval controls; OAuth plugin sandbox and outbound approval channels remain. |
| P11 | Unified React, typed SDK, streaming tests | React workspace builds; legacy screens, generated SDK, cancellation coverage, and browser E2E remain. |
| P12 | Admin, exports, portals, voice, billing | Existing tenant APIs and local voice foundations; branded exports, client portal, sovereign WebRTC, and billing remain. |
| P13 | Portable SSD, safe stop, license, signed bundle | Host-assisted offline Compose profile and guarded stop/checkpoint/backup helper exist; Ed25519 offline license/bundle verification primitives are tested but not wired to startup or an installer. Hardware, bootable-OS, and physical unlock validation remain. |
| P14 | IaC, topology, supply chain, CD | Hardened Compose and CI exist; cloud IaC and release workflow remain. |
| P15 | Load, chaos, pentest, red team | Production contracts exist; load/chaos/red-team harness and authorized execution remain. |
| P16 | Compliance and launch gates | Software controls exist; policy ownership, evidence, independent audit, and launch sign-off remain. |

The architecture playbook's DAG is dependency ordered: P00 → P01 → P02/P03 → P04/P05 → P06/P07/P08 → P09/P10/P11 → P12/P13/P14 → P15 → P16. Recheck the table after each implementation group; do not mark service, hardware, or compliance gates complete from source-code tests alone.

## Verification entry points

- Unit/integration tests: `python -m pytest tests/ -q` (CI supplies synthetic secrets; do not copy real credentials into a test run).
- Production contracts: `python finesse_e2e_production_tests.py`.
- OpenAPI auth drift: `python scripts/export_openapi.py --check`.
- Frontend: `cd frontend && npm ci && npm audit --audit-level=moderate && npm run build`.
- Deployment topology: `deploy/compose.yaml`, `deploy/compose.portable.yaml`, and `deploy/PORTABLE_SSD.md`.
- Source requirements: see the read-only project `sources/` mirror and repository `PRD.md`.
