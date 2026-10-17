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
current source. The open HIGH and MEDIUM items below still make an
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
Lane-scoped searches now query only the caller's lane plus notes marked
`shared` or `global`. The vault search tool receives the trusted lane from the
server-side dispatcher, not from the model.

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
  stores chunk vectors and lane metadata.

### 4. Model inference and agent execution

The asynchronous provider uses OpenAI-compatible APIs:

- NVIDIA NIM is the primary hosted completion provider when configured.
- JARVIS may use a dedicated NIM key or Groq for its short voice responses.
- A configured local OpenAI-compatible endpoint can serve selected heavy
  roles.
- With no completion backend, the app returns an explicit offline stub rather
  than a model-generated answer.

Agents have role-specific system prompts, model roles, token limits, and
optional tool access. Agentic agents can request tools for a bounded number of
steps. Tool access is checked against the agent lane; write/action tools return
a proposal until a human with permission approves them. The optional
self-reflection pass critiques selected outputs before return.

For multi-agent work, `asyncio.gather` runs agents concurrently. A synthesizer
combines multiple results; a one-agent run skips synthesis. A global semaphore,
optional per-lane semaphores, retry/backoff, a small cache for low-temperature
requests, and single-flight deduplication bound some inference pressure. These
are mechanisms, not a throughput guarantee; no 30-user load test was run.

### 5. Memory, output, and training

Deliverables are written into the configured local Obsidian vault. Selected
agent outputs can also contribute a short, shared-memory entry, which is
embedded for later retrieval and appended to a Markdown memory note. This
changes the context available to future prompts; it does **not** update model
weights or independently verify that a remembered claim is true.

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
| H-1 | **HIGH** | Open | Login has no rate limit, lockout policy, or alerting against credential stuffing. User passwords created through the API do not have a minimum-length policy. | Add per-account and per-IP throttling, abuse monitoring, a reset/recovery process, and validation for all newly created passwords. Avoid permanent lockouts that enable denial of service. |
| H-2 | **HIGH** | Open | Prompts, retrieved vault material, and user requests can leave the machine through hosted NIM/Groq and optional TTS/embedding providers. | Define data classifications and provider retention rules; disclose outbound processing; redact sensitive fields; offer an enforceable local-only mode for confidential work. |
| H-3 | **HIGH** | Partially mitigated | Lane retrieval is now strict, but the vector store is still shared and `shared` memory is intentionally visible across lanes. Sensitive inputs or outputs can be copied into shared memory and later retrieved elsewhere. | Add tenant/business-unit isolation, memory approval and redaction, deletion/retention controls, and tests proving a private document cannot appear in another lane's context. |
| H-4 | **HIGH** | Open | Uploaded documents and web/GitHub results are untrusted instructions as well as data. Prompt injection can influence agent output and tool selection. Write tools are approval-gated, but this is not a complete prompt-injection defense. | Keep retrieved content clearly separated and labeled as untrusted; constrain tool arguments and destinations; require confirmation for consequential actions; add adversarial tests and safe-output checks. |
| H-5 | **HIGH** | Open | The application has no deployment-grade TLS, reverse-proxy, or secrets-management setup. It now binds to loopback by default, but setting `APP_HOST` to a public interface exposes the service unless an operator supplies the missing controls. | Keep the loopback default for local use. Before network deployment, require HTTPS at a trusted proxy, firewall rules, secure headers, secret rotation, and documented proxy settings. |
| H-6 | **HIGH** | Partially mitigated | The optional FRIDAY client must authenticate to FINESSE. Credentials can still be stored in its local JSON configuration as plaintext, even though the repository no longer contains credential defaults. | Prefer process environment variables or Windows Credential Manager, use a dedicated least-privilege account, and restrict the local config file's filesystem permissions. |
| M-1 | **MEDIUM** | Open | The JSON user/CRM stores and in-memory session/event state are not transactional or multi-process safe. A single worker and local Qdrant are development-oriented. | Move shared records and sessions to a transactional database, define backup/restore and retention, and test multiple workers before scaling out. |
| M-2 | **MEDIUM** | Open | Runtime error handling in some Hub persistence/dispatch paths suppresses exceptions and can return an idea result even when indexing or dispatch failed. | Return partial-failure status explicitly, log structured diagnostics without sensitive content, and make background task failures observable. |
| M-3 | **MEDIUM** | Open | There is no comprehensive app test suite or model-quality evaluation. The new tests cover important authorization, upload, and retrieval guards, not end-to-end model correctness or concurrency. | Add CI, API/integration tests, role-isolation tests, model-output evaluations, and a reproducible load test. |
| M-4 | **MEDIUM** | Open | Prompt outputs are not schema-validated beyond selected JSON parsing. Factuality, relevance, and lead quality are not measured automatically. | Define structured output schemas, source attribution, quality thresholds, and human review for business-critical conclusions. |
| M-5 | **MEDIUM** | Open | Hosted/server-mode Qdrant is created from a URL without an API key or TLS option in the client setup. | Do not expose Qdrant publicly. Add authenticated TLS configuration and least-privilege network access before enabling server mode. |
| M-6 | **MEDIUM** | Open | The optional training guide reports very small per-lane example counts; small or low-quality datasets can overfit or encode sensitive data. | Review/consent and de-identify training data, keep data out of Git, add held-out evaluation, and document model/license provenance. |
| M-7 | **MEDIUM** | Open | A compressed Office document can expand substantially during parsing even when its uploaded size is within the 10 MiB limit. PDF page counts and spreadsheet rows are not separately bounded. | Parse untrusted documents in a resource-limited worker; enforce page/row/expanded-size limits and reject malformed or unusually large archives. |
| L-1 | **LOW** | Open | `TurboQuant` is the name of a concurrency/cache layer here; it does not quantize the completion model. The performance language can be mistaken for a measured quantization or throughput result. | Describe it as bounded serving/caching, report actual backend quantization separately, and publish benchmarks before making capacity claims. |
| L-2 | **LOW** | Open | No project license is present. A public repository without a license does not grant general reuse rights. | Select and add a license only after the owner decides the intended reuse terms. |
| L-3 | **LOW** | Open | WebSocket authentication uses a query parameter because browser WebSocket APIs cannot set a normal Authorization header. Reverse proxies may log URLs. | Ensure query strings are redacted from logs; consider a short-lived, single-use WebSocket ticket or a secure cookie once HTTPS is deployed. |
| L-4 | **LOW** | Open | Local audit logs can contain tool arguments, are not rotated, and are stored as append-only JSONL without tamper-evident retention. | Minimize logged fields, redact personal data, rotate and protect logs, and define retention/monitoring requirements. |

## Changes made for this publication

- Removed the Hub's hardcoded demo-admin credential path.
- Added authentication and caller-role enforcement for Hub idea submission;
  removed CEO impersonation from Hub-triggered work.
- Restricted cross-organization Hub queue and event-stream access.
- Added authentication to the global event feed and updated browser clients.
- Restricted global graph, innovation-feed, and swarm-session data to
  executive-tier permissions.
- Changed lane retrieval from soft ranking to exact lane/shared/global searches,
  including the `vault_search` tool and JARVIS context.
- Fixed the single-agent execution check so non-executive users cannot run
  executive-lane agents.
- Added upload type/size limits, random temporary filenames, and cleanup.
- Removed embedded account credentials and personal paths from voice/training
  helpers and browser defaults; demo accounts now receive random one-time
  passwords.
- Removed insecure default JWT/CEO passwords; startup now fails unless suitable
  local values are configured.
- Changed the default bind address to `127.0.0.1`, made host/port configurable,
  and removed a personal email from the example environment file.
- Expanded `.gitignore` to exclude runtime data, local vaults, training
  exports, local developer configuration, and the internal handoff file.
- Added focused unit/API regression tests for the critical guards.

## Public repository boundary

The public repository contains source code, dependency manifests, sanitized
configuration examples, and the new README/report only. It excludes `.env`,
`data/` (including prospect spreadsheets, users, audit logs, and Qdrant),
`vault/`, `FINESSE VAULT/`, `training/data/`, `.mcp.json`, `.venv/`, local
editor/agent configuration, `HANDOFF.md`, and the superseded
`ARCHITECTURE.md`. These local files are not deleted or moved.

## Readiness conclusion

The critical source-level access-control issues identified in this review have
been fixed and have regression tests. That does not certify the system as
production-ready. Complete the HIGH items—especially login abuse controls,
provider data governance, shared-memory governance, prompt-injection defenses,
and secure deployment—before exposing a live FINESSE instance to untrusted
networks or using it for confidential data.
