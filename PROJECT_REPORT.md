# FINESSE: Architecture, AI Data Flow, and Prioritized Review

**Review date:** 2026-10-17
**Scope:** source/configuration review of the FINESSE application and the changes
made for public-source publication. No running deployment, provider account,
external network service, or production dataset was tested. This is an
engineering review, not a formal penetration test or compliance assessment.

## Executive summary

FINESSE is a prototype AI orchestration application, not a model trained from
scratch. In its normal runtime it combines hosted or local language-model
inference with local embeddings, vector retrieval, role-based agent prompts,
optional tools, and a shared Markdown knowledge vault. The optional QLoRA
workflow is separate and manually operated.

The reviewed source had multiple critical access-control problems: a demo
credential that could mint a CEO token, unauthenticated idea submission that
launched work as CEO, an unauthenticated global event stream, and an upload
filename path that could escape the upload directory. These are fixed in the
current source. This update also remediates the four targeted tracks:
identity/lane-isolated memory and RAG, taint-aware prompt-injection controls,
sensitivity-aware LLM egress, and production configuration/network defaults.
The remaining HIGH and MEDIUM items below still make an
internet-facing or regulated production deployment inappropriate without
further work.

Local `.env` credentials, business/prospect data, vector databases, and both
local vault folders are intentionally excluded from the public source
repository. No secret values or customer records are included in this report.

## How the AI works

### 1. Request and intent routing

The browser sends a request to FastAPI. Users authenticate through a password
check backed by bcrypt; the server issues an HS256 JWT with a role and tier.
JARVIS can ask a configured model to classify a request into chat, research,
build, lead-generation, security, diagram, or other actions. A direct directive
can instead enter the orchestrator without the voice classifier.

Action handlers now check the caller's permissions for sensitive actions.
Executive-only views and the global WebSocket feed require an executive-tier
token. The server defaults to loopback binding.

### 2. Planning and role-scoped retrieval

For a directive, the orchestrator builds the candidate agent list from the
caller's lane and permissions. A planner model selects agents from that list;
invalid or invented agent keys are discarded. A keyword fallback chooses a
small set if the planner response cannot be parsed. Planner-selected swarms
are capped; explicit user selections use the configured swarm maximum.

Each agent retrieves relevant notes before generating an answer. Retrieval
combines dense vector similarity with a lightweight lexical-overlap score.
Each chunk carries a `lane` and `sensitivity`; access is intersected with
`permitted_lanes()` and the role's sensitivity ceiling in `engine/auth/rbac.py`.
Missing role context falls back to general-lane clearance, and legacy chunks
without the required metadata are denied. Shared/global material is also
subject to its sensitivity ceiling. The vault search tool receives the trusted
lane from the server-side dispatcher, not from the model.

### 3. Embeddings and vector storage

- The default embedding backend is FastEmbed with a local ONNX embedding model.
- If FastEmbed cannot initialize, the code falls back to a deterministic
  hash-based vectorizer; this keeps the service running but gives much weaker
  retrieval.
- An optional NVIDIA embedding backend sends text to the configured hosted
  service.
- Qdrant runs embedded on disk by default. Server mode can be configured with
  `QDRANT_URL`; secure that service separately.
- `python run.py --index` reads Markdown files from the configured vault and
  stores chunk vectors, lane, and sensitivity metadata. Re-index after
  upgrading; old chunks without those fields fail closed.

### 4. Model inference and agent execution

The asynchronous provider uses OpenAI-compatible APIs:

- NVIDIA NIM is the primary hosted completion provider when configured.
- JARVIS may use a dedicated NIM key or Groq for its short voice responses.
- A configured local OpenAI-compatible endpoint can serve selected heavy
  roles.
- With no completion backend, the app returns an explicit offline stub rather
  than a model-generated answer.

Before provider calls, `engine/llm/provider.py` redacts recognized API-key and
Bearer-token patterns, and optionally masks email/phone PII. Callers propagate
RAG sensitivity; confidential/restricted prompts route only to a configured
local endpoint by default, otherwise raising `DataEgressBlocked` before the
network call. `ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS=true` is an explicit policy
override, not a recommended production default. This completion-provider
control does not yet govern optional hosted embeddings or TTS.

Agents have role-specific system prompts, model roles, token limits, and
optional tool access. Agentic agents can request tools for a bounded number of
steps. Tool access is checked against the agent lane; write/action tools return
a proposal until a human with permission approves them. Retrieved text is
wrapped as `<untrusted_content>`; override and fake-tool-call patterns are
flagged without logging the content. External/RAG context taints the agentic
execution state; tainted write tools require a signed, short-lived,
action-and-argument-bound Gatekeeper approval. This is defense in depth, not a
guarantee against all prompt manipulation; read-only tool calls remain possible.
The optional self-reflection pass critiques selected outputs before return.

For multi-agent work, `asyncio.gather` runs agents concurrently. A synthesizer
combines multiple results; a one-agent run skips synthesis. A global semaphore,
optional per-lane semaphores, retry/backoff, a small cache for low-temperature
requests, and single-flight deduplication bound some inference pressure. These
are mechanisms, not a throughput guarantee; no 30-user load test was run.

### 5. Memory, output, and training

Deliverables are written into the configured local Obsidian vault. Selected
agent outputs can also contribute a short memory vector. Memory payloads carry
an owner identity, lane, sensitivity, and inherited taint; retrieval requires
the same owner and permitted role clearance. Conversation history keys include
identity and role/lane, while session listings filter non-executives to their
own runs. Private conversational memory is no longer appended to a shared
Markdown memory note. Memory changes context available to future prompts; it
does **not** update model weights or independently verify a remembered claim.

The separate `training/` workflow exports examples and provides scripts and a
notebook for manual QLoRA experiments. It is not invoked by the running API and
does not automatically deploy a trained adapter. Training examples are
excluded from the public repository.

### 6. Voice and external data flow

Speech recognition runs in the browser. The transcript is submitted to the
server; generated speech uses the browser by default, or a configured external
TTS provider. Hosted LLM, embedding, and TTS providers may receive user text,
retrieved context, or generated speech text. A local embedding model alone
does not keep LLM prompts local.

## Findings and required changes

| ID | Severity | State | Finding / impact | Evidence and recommended action |
| --- | --- | --- | --- | --- |
| C-1 | **CRITICAL** | **Fixed** | The Hub accepted `ADMIN` / `0000` and minted a CEO token, bypassing the user store. | Removed the demo fallback in `engine/hub_api.py`. Keep all demo credentials out of public examples and add a regression test. |
| C-2 | **CRITICAL** | **Fixed** | Unauthenticated Hub idea submission could invoke model work, write to the vault/brain, and dispatch an orchestrator directive under CEO identity. | `/hubapi/problems` now requires a valid JWT, checks that the caller may orchestrate or spawn a permitted lane, and dispatches under that caller's role. Queue reads and Hub streams are executive-only. |
| C-3 | **CRITICAL** | **Fixed** | An uploaded filename was joined directly to the upload path, allowing path traversal and arbitrary file overwrite; the body was also unbounded. | Uploads now accept a defined extension set, enforce a 10 MiB limit, use random server-generated filenames, and remove the temporary file after ingestion. |
| C-4 | **CRITICAL** | **Fixed** | The unauthenticated `/ws` endpoint replayed and streamed organization-wide events, including directive-related metadata. | The stream now requires a signed executive-tier token; the dashboards pass their token only after login. |
| C-5 | **CRITICAL** | **Fixed** | Local account details and weak, fixed demo credentials were embedded in voice/training helpers, browser login defaults, the bundled Hub UI, and the demo-user seeder. Publishing those files would disclose account information and encourage unsafe logins. | Removed credential literals, personal login defaults, and local machine paths; training credentials load from local `.env`; demo passwords are random and one-time. The local credential-bearing configuration is excluded from Git. |
| H-1 | **HIGH** | **Remediated** | Login endpoints lacked abuse throttling; production startup/network defaults did not enforce safe secrets, CORS, or browser security headers. | `engine/main.py` applies failed-attempt limits by source IP and normalized account to `/api/login` and `/hubapi/token`. Forwarded client/protocol headers are honored only from `TRUSTED_PROXY_IPS`. Security headers include HSTS only for HTTPS or verified proxy HTTPS; CORS remains allowlisted and production secrets are validated. Limits are process-local and not suitable for multiple workers; see H-7. |
| H-2 | **HIGH** | **Remediated** | Completion prompts and retrieved context could be sent to hosted models without classification, credential/PII scrubbing, or a local-only path for confidential work. | `engine/llm/provider.py` redacts API-key/Bearer patterns and configurable email/phone PII; caller-supplied and retrieved sensitivity flows through `engine/agents/base.py`, `engine/jarvis_brain.py`, and `engine/hub_api.py`. Confidential/restricted prompts use configured local inference or fail closed unless the explicit cloud-egress override is enabled. Embedding and TTS egress are additionally covered under M-8. |
| H-3 | **HIGH** | **Remediated** | Shared vector retrieval and memory lacked sufficient identity, lane, and sensitivity isolation, allowing role or user context leakage. | `engine/rag/ingest.py` and `scripts/index_vault.py` write lane/sensitivity metadata; `engine/rag/retriever.py` applies role clearance and denies legacy metadata-less chunks. `engine/orchestra/memory.py` scopes vectors by owner and lane; voice history includes identity and role/lane; `engine/orchestra/sessions.py` filters non-executive session state to its owner. Existing vector data must be re-indexed; otherwise missing metadata remains inaccessible. |
| H-4 | **HIGH** | **Remediated** | External and retrieved content could contain prompt overrides or fake tool markup that influenced agent reasoning and tool selection. | `engine/prompt_guard.py` detects common override patterns, logs only the source, escapes and wraps untrusted text. Agent/JARVIS/orchestrator prompts define the passive-data rule. `engine/mcp/base.py` propagates taint and blocks write tools without an action-bound signed Gatekeeper approval. This reduces risk but does not prove model compliance; tool allowlists, argument validation, and human review remain necessary. |
| H-5 | **HIGH** | **Remediated (source-level guardrails)** | A non-loopback production bind could expose the service without TLS proxy controls. | `engine/config.py` rejects non-loopback production `HOST` unless `TRUSTED_PROXY_IPS` is configured or `ALLOW_UNENCRYPTED_PUBLIC_BIND=true` is explicitly set. `engine/main.py` trusts forwarded headers only from allowlisted proxies and adds HSTS for verified HTTPS. FINESSE does not terminate TLS itself; deploy a correctly configured TLS proxy and firewall. |
| H-6 | **HIGH** | Partially mitigated | The optional FRIDAY client must authenticate to FINESSE. Credentials can still be stored in its local JSON configuration as plaintext, even though the repository no longer contains credential defaults. | Prefer process environment variables or Windows Credential Manager, use a dedicated least-privilege account, and restrict the local config file's filesystem permissions. |
| H-7 | **HIGH** | **Remediated (source-level controls)** | Authentication previously used process-local IP-only throttling and did not enforce a strong password lifecycle. | `engine/auth/security.py` and `engine/main.py` track failed attempts by IP and normalized account; trusted proxy rules prevent spoofed forwarded IPs. `engine/auth/users.py` enforces 12-character minimums, rejects known placeholders, and supports authenticated password rotation with a content-free audit event at `/api/auth/change-password`. Limits remain process-local; distributed throttling and account recovery remain deployment/future work. |
| M-1 | **MEDIUM** | Partially mitigated | The JSON user/CRM stores and in-memory event/session state are not transactional or multi-process safe. Session listings are now identity-scoped for non-executives, but state remains volatile and process-local. | Move shared records and sessions to a transactional database, define backup/restore and retention, and test multiple workers before scaling out. |
| M-2 | **MEDIUM** | Open | Runtime error handling in some Hub persistence/dispatch paths suppresses exceptions and can return an idea result even when indexing or dispatch failed. | Return partial-failure status explicitly, log structured diagnostics without sensitive content, and make background task failures observable. |
| M-3 | **MEDIUM** | Open | There is no comprehensive app test suite or model-quality evaluation. The new tests cover important authorization, upload, and retrieval guards, not end-to-end model correctness or concurrency. | Add CI, API/integration tests, role-isolation tests, model-output evaluations, and a reproducible load test. |
| M-4 | **MEDIUM** | Open | Prompt outputs are not schema-validated beyond selected JSON parsing. Factuality, relevance, and lead quality are not measured automatically. | Define structured output schemas, source attribution, quality thresholds, and human review for business-critical conclusions. |
| M-5 | **MEDIUM** | Open | Hosted/server-mode Qdrant is created from a URL without an API key or TLS option in the client setup. | Do not expose Qdrant publicly. Add authenticated TLS configuration and least-privilege network access before enabling server mode. |
| M-6 | **MEDIUM** | Open | The optional training guide reports very small per-lane example counts; small or low-quality datasets can overfit or encode sensitive data. | Review/consent and de-identify training data, keep data out of Git, add held-out evaluation, and document model/license provenance. |
| M-7 | **MEDIUM** | Open | A compressed Office document can expand substantially during parsing even when its uploaded size is within the 10 MiB limit. PDF page counts and spreadsheet rows are not separately bounded. | Parse untrusted documents in a resource-limited worker; enforce page/row/expanded-size limits and reject malformed or unusually large archives. |
| M-8 | **MEDIUM** | **Remediated** | Hosted embedding and TTS clients were outside credential/PII scrubbing and confidential-data egress controls. | `engine/llm/provider.py` exposes shared scrubbing and egress-policy helpers. `engine/rag/embeddings.py` scrubs hosted requests and routes confidential/restricted embedding to deterministic offline hash generation, avoiding hosted requests and model downloads; `engine/rag/store.py` passes chunk sensitivity into embedding calls and conservatively treats search queries as confidential. `engine/main.py` carries sensitivity resolved by JARVIS/RAG into dashboard TTS requests; `engine/voice_tts.py` scrubs external speech text, defaults omitted classifications to confidential, and blocks confidential/restricted cloud speech unless the explicit egress override is set. |
| L-1 | **LOW** | Open | `TurboQuant` is the name of a concurrency/cache layer here; it does not quantize the completion model. The performance language can be mistaken for a measured quantization or throughput result. | Describe it as bounded serving/caching, report actual backend quantization separately, and publish benchmarks before making capacity claims. |
| L-2 | **LOW** | Open | No project license is present. A public repository without a license does not grant general reuse rights. | Select and add a license only after the owner decides the intended reuse terms. |
| L-3 | **LOW** | Open | WebSocket authentication uses a query parameter because browser WebSocket APIs cannot set a normal Authorization header. Reverse proxies may log URLs. | Ensure query strings are redacted from logs; consider a short-lived, single-use WebSocket ticket or a secure cookie once HTTPS is deployed. |
| L-4 | **LOW** | Open | Local audit logs can contain tool arguments, are not rotated, and are stored as append-only JSONL without tamper-evident retention. | Minimize logged fields, redact personal data, rotate and protect logs, and define retention/monitoring requirements. |

## Hardening changes

- Removed the Hub's hardcoded demo-admin credential path.
- Added authentication and caller-role enforcement for Hub idea submission;
  removed CEO impersonation from Hub-triggered work.
- Restricted cross-organization Hub queue and event-stream access.
- Added authentication to the global event feed and updated browser clients.
- Restricted global graph and innovation-feed access to executive-tier
  permissions; scoped session listings by owner and role clearance.
- Added lane and sensitivity metadata validation to `engine/rag/store.py`,
  `engine/rag/ingest.py`, and `scripts/index_vault.py`; strict role/clearance
  filtering and owner-isolated memory retrieval now fail closed on old
  metadata-less points.
- Scoped JARVIS conversation history by user, role, and lane; removed private
  memory writes into the shared Markdown memory note.
- Wrapped retrieved and external tool content in structural untrusted-data
  tags, flagged common injection patterns, and propagated taint to tool
  dispatch. A signed, short-lived approval is bound to the approved actor,
  tool, and canonical argument hash before tainted write actions execute.
- Added completion-provider credential/PII scrubbing and sensitivity-based
  local-only routing or an explicit pre-egress block for confidential data.
- Added `FINESSE_ENV`, fail-fast production secret validation, loopback
  `HOST`/`PORT` defaults, an environment-driven CORS allowlist, standard
  security headers, and in-memory login throttling.
- Fixed the single-agent execution check so non-executive users cannot run
  executive-lane agents.
- Added upload type/size limits, random temporary filenames, and cleanup.
- Removed embedded account credentials and personal paths from voice/training
  helpers and browser defaults; demo accounts now receive random one-time
  passwords.
- Removed insecure default JWT/CEO passwords; production startup now fails
  unless suitable non-placeholder values are configured, while development
  mode logs a critical warning.
- Changed the default bind address to `127.0.0.1`, made host/port configurable,
  and removed a personal email from the example environment file.
- Expanded `.gitignore` to exclude runtime data, local vaults, training
  exports, local developer configuration, and the internal handoff file.
- Added 27 security-hardening tests for RAG and memory isolation, prompt
  injection, tainted writes, LLM/embedding/TTS egress, account/IP throttling,
  password rotation, legacy-vector audit/purge, production bind validation,
  proxy trust, and HSTS, alongside the existing API guards.

## Public repository boundary

The public repository contains source code, dependency manifests, sanitized
configuration examples, and the new README/report only. It excludes `.env`,
`data/` (including prospect spreadsheets, users, audit logs, and Qdrant),
`vault/`, `FINESSE VAULT/`, `training/data/`, `.mcp.json`, `.venv/`, local
editor/agent configuration, `HANDOFF.md`, and the superseded
`ARCHITECTURE.md`. These local files are not deleted or moved.

## Readiness conclusion

The four requested hardening tracks are implemented and covered by focused
regression tests. That does not certify the system as production-ready.
Complete remaining HIGH/MEDIUM work—especially TLS/reverse-proxy deployment,
distributed login throttling/password lifecycle, hosted embedding/TTS egress,
and durable storage—before exposing FINESSE to untrusted networks or using it
for regulated data. Re-index existing vector collections so new lane and
sensitivity metadata is populated; legacy points are intentionally denied.
