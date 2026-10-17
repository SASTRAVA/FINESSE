# FINESSE

FINESSE is a Python AI workspace for SASTRAVA. It combines role-aware AI agents,
retrieval-augmented generation (RAG), a local Qdrant knowledge store, an
orchestrator, a FastAPI service, and browser dashboards.

> **Status:** prototype / development software. It is not yet hardened or
> load-tested for internet-facing or regulated production use. See
> [PROJECT_REPORT.md](PROJECT_REPORT.md) for the architecture, data flows, and
> prioritized findings.

## What it does

- Accepts human directives and selects one or more permitted agents.
- Retrieves relevant, lane-scoped notes from an Obsidian Markdown vault and
  shared memory.
- Calls hosted NVIDIA NIM (or an optional local OpenAI-compatible server) to
  plan, reason, use read tools, and produce a deliverable.
- Stores vectors in local Qdrant and writes deliverables and selected memory
  back to the configured vault.
- Provides a FastAPI API, a JARVIS-style browser interface, a typed React
  operator workspace, and a live event stream.
- Keeps external write tools behind an explicit approval step.
- Provides SASTRAVA service catalogs, six lane-scoped consulting specialists,
  public website/GitHub knowledge sync, and Listen → Shape → Deliver workflows.

The normal runtime does **not** train model weights. Its "learning" is RAG:
it stores selected text in the vector database for later retrieval. Separate
QLoRA scripts and a notebook provide an optional, manually operated training
workflow; they are not automatically run or deployed by the app.

## Safe-platform foundations

The enterprise additions are deliberately foundations, not a claim of a
production SaaS deployment. Signed JWTs carry a `tenant_id`; new users default
to the `default` tenant unless an authorized administrator assigns another
tenant. Tenant identity is propagated through RAG, orchestration, memory,
sessions, Hub queues, CRM views, and platform records. Tenant-specific
deliverables are written under a tenant-scoped vault directory. Global vault,
audit, and event-stream routes remain restricted to the default tenant rather
than returning cross-tenant data.

The conjunction engine selects review-only workflow plans and explicitly
reports that it performed no external side effects. `engine/db/storage.py` provides tenant-keyed SQLite JSON persistence by
default. When `DATABASE_URL` uses PostgreSQL, it stores JSONB records and sets
`app.current_tenant_id` transaction-locally on every operation; PostgreSQL RLS
policies are installed on the tenant tables. `REDIS_URL` enables shared
account/IP login throttling. Legacy session, account, audit, and runtime state
is still partly file-backed or process-local.

Sales lead generation uses deterministic synthetic records while
`SALES_DRY_RUN=true` (the default). Email and voice adapters, enrichment, and
calendar synchronization are opt-in; live effects require separate enable
flags, tenant consent/suppression checks, and explicit user authorization.
Provider credentials can be encrypted at rest with `KMS_MASTER_KEY`. Calendar
invites can be produced locally as RFC 5545 ICS without syncing externally.
Security tooling creates authorized review plans and does not run scanners;
the security worker only advances plans to human review. Repository catalog
seeds are marked discovered/source-inventory-only, not certified.

Authenticated human-confirmed pattern learning is available at
`POST /api/v1/memory/patterns`. The route requires an explicit
`human_confirmed=true`, stores the authenticated tenant/owner/lane scope, and
does not accept a taint override.

## SASTRAVA consulting workflows

The consulting layer organizes work around six public service lines:
strategy and incubation, AI and automation, software delivery, cybersecurity,
digital growth, and digital learning. Workflow responses separate discovery
(`Listen`), a bounded approach (`Shape`), and a reviewable plan (`Deliver`);
they distinguish evidence from assumptions and do not promise outcomes.

After authentication, the UI offers consulting entry points from the main
dashboard and executive command page. The API also exposes:

- `GET /api/sastrava/catalog` — public services, pillars, playbooks, and
  sanitized source catalogs.
- `POST /api/sastrava/intake` — lane-checked service-line intake and planning.
- `POST /api/sastrava/security-scope` — security scoping; requires a security
  permission and an explicit authorization attestation. It does not execute
  tests or scans.
- `POST /api/sastrava/learning-plan` — audience-led learning plan generation.

The CRM tags leads with validated service-line identifiers. Outreach remains
human-approved.

Sync public knowledge into the sanitized, tracked catalog and local RAG store:

```powershell
python scripts/sync_sastrava_site.py
python scripts/sync_sastrava_github.py
```

The website sync is constrained to `sastrava.com` and its sitemap (with a
small fallback URL list). The GitHub sync reads only repositories explicitly
marked public under the SASTRAVA account, excludes `FINESSE`, and stores only
sanitized repository summaries rather than cloning source code. Both syncs
redact credentials, contact details, and local paths before writing tracked
catalog files. Add `--no-index` to refresh the files without changing vectors.
The bundled playbooks are indexed with `lane=general` and `sensitivity=public`;
indexing does not copy these resources into the private vault.

## How a request flows

1. A user signs in and submits a typed or spoken request.
2. JARVIS can classify the request, or the API can send it directly to the
   orchestrator.
3. The planner chooses from the requester's permitted agent lanes. Agents
   retrieve lane-specific and explicitly shared context.
4. Agents call the configured language model and, where enabled, lane-allowed
   tools. Results are combined into a deliverable.
5. The app writes the deliverable to the local Obsidian vault and may store a
   short shared-memory entry for later retrieval.

Hosted-model requests can include the user's prompt and retrieved context.
Review provider retention and data-processing terms before using confidential
information. Local embeddings do not make hosted LLM calls private; configure
a local LLM endpoint if data must stay on your machine.

## Requirements

- Windows, macOS, or Linux
- Python 3.11 or 3.12
- A language-model API key for real hosted inference (optional for offline
  stub mode)
- Internet access the first time the local embedding model is downloaded

## Quick start (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally:

1. Set a randomly generated `JWT_SECRET` (at least 32 characters).
2. Set a strong `CEO_PASSWORD` (at least 12 characters).
3. Set `CEO_EMAIL` to the account you will use.
4. Optionally set `NVIDIA_API_KEY` for hosted NIM inference. Without it, the
   application runs in offline stub mode.
5. Keep `HOST=127.0.0.1` unless you have deliberately configured a secure
   reverse proxy and firewall. The default `CORS_ORIGINS` allowlist is limited
   to local development origins.
   For production behind TLS termination, set `TRUSTED_PROXY_IPS` to the
   proxy's exact IP addresses. Forwarded client/protocol headers are ignored
   unless the immediate peer is allowlisted. `ALLOW_UNENCRYPTED_PUBLIC_BIND`
   defaults to `false`; only set it to `true` as a conscious deployment
   override.
6. Leave `ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS=false`. Confidential or restricted
   prompts require `LOCAL_LLM_BASE_URL`; FINESSE blocks the request before any
   hosted LLM call if a local endpoint is unavailable. Hosted embeddings use a
   deterministic offline hash backend for confidential/restricted text. TTS
   requests default to confidential sensitivity and hosted speech is blocked at
   confidential/restricted levels unless explicitly allowed.
7. Keep `REDACT_PII_ON_EXTERNAL_LLM=true` to mask emails and phone numbers in
   provider-bound messages, embeddings, and cloud TTS. Recognized API keys and
   bearer tokens are always redacted before external-provider requests.

   `SALES_DRY_RUN=true` keeps legacy and enterprise lead generation on synthetic
   records. Leave `SALES_LIVE_OUTREACH_ENABLED=false`; enabling it does not
   configure a delivery provider, but it is reserved for explicitly reviewed
   future adapters. The optional `REDIS_URL` enables shared login-throttle state;
   without Redis, throttling is process-local.

Requests and ingestion endpoints that accept data can include a `sensitivity`
value (`public`, `internal`, `confidential`, or `restricted`); omitted values
default to `internal`. Treat this label as a security boundary and classify
uploaded material conservatively.

For production, set `FINESSE_ENV=production` and provide a non-placeholder
`JWT_SECRET` (at least 32 characters) and `CEO_PASSWORD` (at least 12
characters). Startup fails if either value is missing, too short, or matches a
known placeholder. Set `HOST`, `PORT`, and `CORS_ORIGINS` explicitly for the
deployment; do not bind publicly without TLS, a trusted reverse proxy, and
firewall controls.
Persistent runtime state defaults to `./data`; `FINESSE_DATA_DIR` can relocate
it when the deployment needs a separate protected storage volume.

Generate a JWT secret:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Index your own Markdown vault (optional; do not index material you are not
authorized to process):

```powershell
python run.py --index
```

Audit old Qdrant points that lack valid lane/sensitivity metadata without
modifying them:

```powershell
python run.py --index --audit-only
```

Purge only those legacy points before indexing the vault again:

```powershell
python run.py --index --purge-legacy
```

The indexer flags are mutually exclusive. `--audit-only` reports a count and
exits; `--purge-legacy` removes the flagged points, then proceeds with indexing.
Indexing also adds the bundled SASTRAVA playbooks and any generated public
catalogs to RAG; those sources are tagged `general` and `public`.

Start FINESSE:

```powershell
python run.py
```

Open `http://127.0.0.1:8600`; use `/workspace/` for the React workspace, `/`
and `/command` for the standalone dashboards. Node is only needed when changing
the frontend source:

```powershell
cd frontend
npm ci
npm run build
```

The built workspace is served by FastAPI and the standalone HTML dashboards
link to it. Its typed React/Vite source lives in `frontend/`.

## Deploy to Vercel (Live Website Quickstart)

Vercel serves the Python FastAPI app through `api/index.py` and builds the
React/TypeScript workspace from `frontend/`. The root [vercel.json](vercel.json)
contains the build command, routing rewrites, and baseline security headers.

1. Import `SASTRAVA/FINESSE` into Vercel and keep the project Root Directory at
   `.`. Use FastAPI/Python framework detection (or Other); do not configure a
   second build or output directory in the dashboard because `vercel.json`
   provides both. Vercel CLI 48.1.8 or newer is required for local `vercel dev`.
2. Add these Environment Variables to **Preview** and **Production** (and
   Development if you use Vercel CLI):
   - `CEO_EMAIL` — the initial administrator account.
   - `CEO_PASSWORD` — unique password, at least 12 characters and no more than
     bcrypt's 72-byte limit.
   - `JWT_SECRET` — independently generated random value of at least 32 bytes.
   - `KMS_MASTER_KEY` — separate random value of at least 32 bytes for
     encrypting provider credentials.
3. Optionally configure `NVIDIA_API_KEY`, `GROQ_API_KEY`, `DATABASE_URL` (a
   managed PostgreSQL URL), `QDRANT_URL` (a managed Qdrant URL), and
   `REDIS_URL`. Vercel-provided `VERCEL_URL` and
   `VERCEL_PROJECT_PRODUCTION_URL` are automatically added to the CORS
   allowlist. Add a custom frontend origin to `CORS_ORIGINS` if it is not
   represented by those Vercel hostnames.

For local serverless-style testing, install the Vercel CLI and run
`vercel dev` from the repository root after configuring Development variables.
Test `/api/health`, `/api/v1/platform/runtime`, `/workspace/`, `/dashboard`,
`/command`, and `/jarvis`.

Vercel's `/tmp` storage is writable but ephemeral and isolated per function
instance. FINESSE automatically puts local data, vault, and Qdrant files there
when their paths are not overridden. Cold starts bootstrap the CEO and public
catalog from configured environment values. For shared durable platform
records, configure managed PostgreSQL; for shared durable vectors, configure
managed Qdrant. The legacy account JSON store and vault files remain
instance-local/ephemeral, so do not rely on Vercel filesystem state for durable
user provisioning, password changes, uploads, or generated vault documents.
The runtime status badge reports whether required setup is present and whether
sales providers remain in dry-run mode.

Local vault content, uploads, user records,
vector data, audit logs, and credentials are intentionally excluded from this
public source repository. Point `VAULT_PATH` at a vault you control; do not
publish that vault.

### Opt-in providers

Every provider defaults to sandbox/local behavior. Live email requires
`SALES_DRY_RUN=false`, `SALES_LIVE_OUTREACH_ENABLED=true`, and
`EMAIL_LIVE_ENABLED=true`, an approved draft/campaign, current
`email_campaign` or `email_marketing` consent, and a non-suppressed contact.
Select `EMAIL_PROVIDER=smtp` with STARTTLS settings or `webhook` with an
HTTPS public endpoint. Calls additionally require `VOICE_LIVE_ENABLED=true`,
an explicit parsed call command, written `voice_call` consent, a verified
eligible contact, a fixed approved disclosure script, a single-use
Gatekeeper approval, and allowed calling hours. Twilio is the only live voice
adapter. Do not use synthetic sandbox leads for live outreach.
For Twilio, set `VOICE_WEBHOOK_URL` to the public HTTPS
`/api/v1/webhooks/providers/voice` endpoint. Status callbacks validate
`X-Twilio-Signature` against that exact URL and the tenant's Twilio auth token.
Calls include a signed tenant/contact-scoped Gather callback at
`/api/v1/webhooks/providers/voice/opt-out`; saying "stop" (or pressing 9)
records a tenant-scoped suppression entry. The callback handlers store status
and opt-out metadata only, not speech transcripts.

Enrichment is disabled unless `SALES_ENRICHMENT_ENABLED=true`; it sends only a
consented company's domain to the configured HTTPS endpoint. Calendar is local
by default (`CALENDAR_PROVIDER=local`); ICS creation does not contact a
provider. External calendar webhooks additionally require
`CALENDAR_SYNC_ENABLED=true`, explicit sync confirmation, recorded calendar
consent, HTTPS, and an idempotency key. Generic JSON callbacks must include a
valid `X-Finesse-Signature: sha256=<hex>` HMAC-SHA256 signature; Twilio form
callbacks use `X-Twilio-Signature` validation instead. Email and voice opt-outs
create a tenant-scoped suppression record; raw webhook transcripts/content
are not stored. Non-default tenants must configure their own encrypted
provider signing keys and Twilio auth token; `WEBHOOK_SIGNING_SECRET` is only
a fallback for generic callbacks from the `default` tenant.

For per-tenant credentials, use the CEO/COO-only provider-secret API; a
random, independently managed `KMS_MASTER_KEY` (at least 32 bytes) is required
for AES-GCM envelope encryption. Keep the master key outside the database and
back it up separately. Global environment credentials remain an optional
operator-managed fallback.

### PostgreSQL, Redis, and rootless deployment

SQLite remains the local default. To use PostgreSQL, set `DATABASE_URL` to a
`postgres://` or `postgresql://` connection and apply
`migrations/001_multi_tenant_rls.sql` after the tenant tables exist. Every
storage operation binds its trusted tenant ID in the transaction using
parameterized `set_config('app.current_tenant_id', ..., true)`; deploy with a
database role that is not a superuser and does not have `BYPASSRLS`. Use Redis
via `REDIS_URL` for shared login throttling across API workers.

The rootless Compose deployment and operations runbook are in
[`deploy/`](deploy/README.md). It publishes the API only on host loopback and
uses non-root processes, read-only root filesystems, dropped Linux
capabilities, and `no-new-privileges`. Set a random `POSTGRES_PASSWORD`,
production auth secrets, and the exact TLS proxy IP in `TRUSTED_PROXY_IPS`;
production startup intentionally rejects a non-loopback bind without a
trusted proxy or explicit override. Provider live flags remain off in Compose.
The security worker cannot execute scans; it only marks authorized plans for
operator review.

## Useful commands

```powershell
python run.py --index       # index Markdown files in the configured vault
python run.py --seed        # create demo users with one-time random passwords
python run.py --reweave     # rebuild Obsidian links
python run.py --manifest    # regenerate the vault manifest
python -m unittest discover -s tests
```

The seed command prints each new demo password once; it is intended only for
local testing, not production accounts.

## Main components

| Path | Purpose |
| --- | --- |
| `engine/main.py` | FastAPI endpoints, authentication, uploads, WebSocket |
| `engine/auth/` | JWTs, password hashing, role and permission definitions |
| `engine/agents/` | Agent prompts, registry, execution |
| `engine/orchestra/` | Planning, concurrent agent runs, synthesis, event bus, memory |
| `engine/db/storage.py` | Tenant-keyed SQLite JSON records and transaction helpers |
| `engine/db/tenant_secrets.py` | Per-tenant AES-GCM encrypted provider credentials |
| `engine/sales/providers.py` | Opt-in email, voice, enrichment, calendar, and webhook adapters |
| `engine/orchestra/langgraph_conjunction.py` | Deterministic review-only workflow planning |
| `engine/sales/` | Synthetic sandbox sales flows, drafts, scoring, and tenant APIs |
| `engine/rag/` | Embeddings, vector storage, retrieval, ingestion |
| `engine/llm/` | Hosted/local model routing, retries, cache and concurrency bounds |
| `engine/mcp/` | Lane-aware tools and approval gate for write tools |
| `engine/prompt_guard.py` | Untrusted-content wrapping and injection-pattern detection |
| `engine/knowledge/` | Sanitized public catalogs, SASTRAVA service lines, and playbooks |
| `engine/sastrava/` | Consulting workflow construction and service-line routing |
| `engine/web/` | Standalone dashboards and built React operator workspace |
| `frontend/` | Typed React 19 / TypeScript / Vite workspace source |
| `deploy/` | Rootless Compose, container image, and operational runbook |
| `scripts/` | Vault indexing, public-source sync, and local demo-user utilities |
| `training/` | Optional dataset export and QLoRA workflows |
| `voice/` | Optional standalone voice client |

## Security and privacy

- Never commit `.env`, local vaults, user data, CRM exports, training examples,
  or runtime databases.
- `.gitignore` excludes local data and the workspace's private vault folders.
- The server defaults to loopback binding. Do not expose it directly to the
  internet.
- Uploaded files are limited to 10 MiB and stored under random temporary names.
- RAG chunks are indexed with `lane` and `sensitivity` metadata. Retrieval
  applies the authenticated role's lane/clearance, defaults to least privilege
  when context is missing, and rejects legacy chunks lacking required metadata.
  Re-index existing vault data with `python run.py --index` after upgrading.
- Conversation memory and swarm sessions are scoped to the authenticated
  identity and role/lane. Executive-only memory remains inaccessible to
  non-executives; private memory is not written into the shared vault note.
- Retrieved material is delimited as `<untrusted_content>` data. Prompt
  override/fake-tool patterns are flagged, external tool results taint the
  execution context, and tainted MCP writes require a short-lived,
  action-bound signed Gatekeeper approval.
- Hosted LLM, embedding, and TTS egress share credential/PII scrubbing.
  Confidential/restricted chat and embedding requests stay local by default;
  cloud TTS is blocked unless confidential egress is explicitly enabled.
- Login endpoints track failed attempts by both client IP and normalized
  account. `X-Forwarded-For` and `X-Forwarded-Proto` are trusted only from
  `TRUSTED_PROXY_IPS`. Authenticated password rotation is available at
  `POST /api/auth/change-password`; it requires the current password and a
  new password of at least 12 characters. Rate-limit state remains
  process-local; use a shared gateway limiter for multi-worker or distributed
  deployments.
- Production startup rejects non-loopback binds unless a trusted TLS proxy IP
  is configured or `ALLOW_UNENCRYPTED_PUBLIC_BIND=true` is explicitly set.
  HSTS is added only for direct HTTPS requests or verified proxy HTTPS.
- Executive-only endpoints and the global event stream require executive
  authorization.
- Review the remaining open deployment, retention, TLS, multi-worker, and
  evaluation concerns in [PROJECT_REPORT.md](PROJECT_REPORT.md) before
  production use. Configure sensitivity correctly when ingesting content; do
  not downgrade confidential data to make hosted inference available.

## License

No license has been added. Until the owner chooses one, the repository is
publicly viewable but reuse and redistribution are not granted by an open-source
license.
