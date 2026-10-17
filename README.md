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
- Provides a FastAPI API, a JARVIS-style browser interface, and a live event
  stream.
- Keeps external write tools behind an explicit approval step.

The normal runtime does **not** train model weights. Its "learning" is RAG:
it stores selected text in the vector database for later retrieval. Separate
QLoRA scripts and a notebook provide an optional, manually operated training
workflow; they are not automatically run or deployed by the app.

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

Start FINESSE:

```powershell
python run.py
```

Open `http://127.0.0.1:8600`. Local vault content, uploads, user records,
vector data, audit logs, and credentials are intentionally excluded from this
public source repository. Point `VAULT_PATH` at a vault you control; do not
publish that vault.

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
| `engine/rag/` | Embeddings, vector storage, retrieval, ingestion |
| `engine/llm/` | Hosted/local model routing, retries, cache and concurrency bounds |
| `engine/mcp/` | Lane-aware tools and approval gate for write tools |
| `engine/prompt_guard.py` | Untrusted-content wrapping and injection-pattern detection |
| `engine/web/` | Browser dashboard pages and bundled Hub UI |
| `scripts/` | Vault indexing and local demo-user utilities |
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
