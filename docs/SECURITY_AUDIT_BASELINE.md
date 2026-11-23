# Security audit baseline

**Scope:** source/configuration review for the P00–P05 work currently present in this checkout. No production account, customer dataset, provider credential, or internet-facing deployment was tested. This is not a penetration test, SOC 2 report, GDPR/DPDP assessment, or hardware certification.

## Confirmed controls

- Route authorization is declared through FastAPI bearer dependencies. The generated matrix at `docs/security/route_auth_inventory.json` classifies each HTTP operation and gives every unauthenticated operation an explicit public-access rationale. CI checks it for drift.
- PostgreSQL data operations bind tenant ID with transaction-local `set_config`; the runtime verifies PostgreSQL version, role attributes, RLS, forced RLS, and policy coverage for platform tables. Local SQLite uses WAL, `synchronous=FULL`, and a busy timeout.
- Vector retrieval supplies tenant and lane filters and rechecks tenant, lane, sensitivity, and owner metadata before prompt assembly. Cloud LLM calls have sensitivity blocking and secret/optional-PII scrubbing.
- Gatekeeper approvals and provider callbacks have signature, tenant, replay, and human-approval controls covered by existing contract tests.
- Browser event streams now use hashed, expiring, single-use ticket records; long-lived JWTs are no longer placed in FINESSE operator WebSocket URLs. Both stream handlers require an allowlisted `Origin` before accept.
- Successful login, password change, and user creation are written to per-tenant hash chains. PostgreSQL migration `003_hash_chained_audit.sql` applies RLS and blocks update/delete on audit events; SQLite tests enforce append-only triggers.
- File uploads are capped at 10 MiB, checked against content signatures, and Office archives are rejected for path traversal, encryption, extreme expansion, excessive entries, or oversized members before format parsing.

## Residual risks and unverified requirements

- The PostgreSQL user store uses the current tenant-keyed JSONB record table. A normalized identity schema, legacy-user migration in a live database, and pooled two-tenant PostgreSQL stress test have not been completed.
- WebSocket tickets are consumed from the configured platform database. Redis-backed ticket TTL/session revocation and Redis cross-replica stream behavior still require live Redis tests. Hub idea state remains partly in process memory.
- The hash-chained log currently captures login success, password change, and user creation. It does not yet capture every sensitive API action; the current audit views and event bus are not a substitute for a complete independently retained audit program.
- Document ingestion is bounded and parser work runs off the event loop, but it is still a synchronous request/response operation rather than a durable queue handoff. S3-compatible vault storage and worker/DLQ deployment are not present.
- OIDC/SAML, MFA enforcement, SCIM, key rotation, MCP OAuth, export/billing integrations, and verified supply-chain releases are not implemented in this construction slice.
- Public routes are intentionally enumerated in the route inventory. Reassess their rationale if their response content or behavior changes.
- Production PostgreSQL, Redis, remote Qdrant, backup restoration, performance, chaos, and adversarial testing were not run in this host session.

## Required follow-up before production exposure

1. Complete and review normalized identity/session persistence and data migration.
2. Exercise RLS using the deployed non-owner, non-superuser application role and alternating pooled tenant transactions.
3. Validate Redis, Qdrant, database backup and restore, secret rotation, and all replica behaviors in a staging environment.
4. Run authorized external security testing and formally approve retention, privacy, incident response, subprocessors, and compliance evidence.
5. Validate the chosen SSD, encryption mechanism, host OS, unplug recovery, and bootable-image requirements on physical hardware.
