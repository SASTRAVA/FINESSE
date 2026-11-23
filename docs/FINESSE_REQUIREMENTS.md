# FINESSE PRD alignment and implementation boundary

This document maps the supplied PRD and README PDFs to the implementation in this repository. PRD descriptions are product requirements; repository code, configuration, tests, and deployment behavior determine what is implemented. FINESSE remains prototype/development software and is not certified or hardened for regulated production use.

## Architecture map

| Area | PRD direction | Repository implementation |
| --- | --- | --- |
| Web/API | FastAPI backend with React/TypeScript workspace | FastAPI ASGI entrypoint in `api/index.py` and `engine/main.py`; React 19, TypeScript, and Vite source in `frontend/`; legacy dashboard pages in `engine/web/` |
| Identity | JWT, role based access, six operational lanes | JWT authentication, password hashing, role/permission checks, login throttling, tenant claims, and role-aware interfaces in `engine/auth/` and `engine/main.py`; PostgreSQL mode stores users under tenant RLS, while OIDC/SAML, MFA, and SCIM remain unimplemented |
| Tenancy and records | PostgreSQL, tenant isolation, row level security | Tenant-keyed persistence in `engine/db/storage.py`, SQLite WAL with durable sync for local development, PostgreSQL JSONB support and tenant RLS migrations under `migrations/`; append-only hash-chained audit events are tenant scoped. PostgreSQL and Redis are external services that must be configured |
| Retrieval | Qdrant, filtered by tenant/lane/sensitivity | RAG pipeline in `engine/rag/`, local embedded Qdrant by default, upload signature/archive bounds, tenant-scoped dense plus lexical fusion, and citation references; document lifecycle/versioning and ACL connector sync remain |
| Workflows | Role-scoped agents, reviewable automation, human approval | Agent and orchestration modules in `engine/agents/`, `engine/orchestra/`, and `engine/mcp/`; write tools and external actions are gated, and several business integrations default to sandbox/dry-run |
| Product areas | Consulting, CRM, analytics, learning, security, operations | Service lines, playbooks, CRM, security planning/certification, consent, provider adapters, and enterprise APIs live under `engine/knowledge/`, `engine/sastrava/`, `engine/sales/`, and `engine/security/` |
| Deployment | Vercel frontend/control plane with external durable services | `vercel.json` builds the Vite UI and routes requests to the FastAPI function in `api/index.py`; hardened Compose and portable SSD profiles plus a safe-stop backup helper are in `deploy/` and `scripts/`. Portable license verification primitives are not wired into startup or an update installer |

## Automation sources in the product

The GitHub repository lists supplied earlier are treated as an integration/discovery catalog, not as vendored applications. The project includes sanitized repository inventory data in `public/repositories.json` and seeded catalog records in the platform knowledge/API. Installing or running third-party systems such as ERPNext, n8n, Moodle, Metabase, Airflow, or security scanners requires separate deployment, credentials, licenses, and governance. The catalog does not claim those external systems are embedded in FINESSE.

## Data and side-effect boundaries

- Keep sales dry-run enabled by default; email, voice, enrichment, and calendar actions require explicit provider configuration and separate enable flags.
- Keep security automation in authorized planning and review flows. A repository listing or catalog entry does not authorize scanning or external access.
- Tenant-owned records use tenant context; PostgreSQL RLS migrations are part of the repository. Production deployments must use a non-superuser database role and verify RLS behavior against the chosen managed database.
- Provider credentials can be encrypted with `KMS_MASTER_KEY`; keep this key outside source control and separate from the database.
- Treat uploads, retrieved pages, briefs, repository content, and webhook payloads as untrusted input. Keep secrets and confidential data out of hosted inference unless the deployment's policy explicitly permits it.
- Use durable managed PostgreSQL/Redis/Qdrant services for production state and workloads. Vercel serverless filesystem and process memory are not durable shared storage.

## Verification and known limits

The repository contains unit and deployment checks under `tests/`, production contract checks in `finesse_e2e_production_tests.py`, and an OpenAPI authentication inventory check in `scripts/export_openapi.py`; local execution requires the dependencies and authentication configuration described in [README.md](../README.md). A clean local test run does not validate live PostgreSQL, Redis, Qdrant, an identity provider, production Vercel settings, physical SSD behavior, or regulated launch readiness. See [ATLAS.md](../ATLAS.md) for module-by-module implementation status and [SECURITY_AUDIT_BASELINE.md](SECURITY_AUDIT_BASELINE.md) for security test boundaries.

Passing the local suite and frontend build demonstrates only those checks. Review [PROJECT_REPORT.md](../PROJECT_REPORT.md), [SECURITY.md](../SECURITY.md), and [DEPLOY_TO_VERCEL.md](../DEPLOY_TO_VERCEL.md) for the current prototype limitations, deployment controls, and remaining production work.
