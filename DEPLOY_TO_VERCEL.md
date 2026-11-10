# Deploy FINESSE to Vercel

This is the deployment and production-readiness runbook for the SASTRAVA/FINESSE repository. Vercel serves the FastAPI application from `api/index.py` and builds the React operator workspace from `frontend/`. The repository is not deployable as a complete production backend until PostgreSQL 16, Redis 7, remote Qdrant, and production secrets are provisioned and available to the production function.

## 1. Verify and push the code

Use a clean clone of `https://github.com/SASTRAVA/FINESSE` if the current directory is not a Git checkout. Run these commands from the repository root after reviewing the staged diff:

```bash
git switch main
git pull --ff-only origin main
git status --short
git add .
git diff --cached --check
python -m pytest tests/ -v
python finesse_e2e_production_tests.py
cd frontend && npm ci && npm run build && cd ..
git diff --cached --stat
git commit -m "Complete production readiness and deployment contract"
git push origin main
```

Prefer a review branch and pull request when repository branch protection requires checks. The GitHub Actions workflow in `.github/workflows/ci.yml` runs on `main` pushes and pull requests. A successful push to the connected production branch should start a Vercel deployment automatically; verify its commit SHA and result in the Vercel Deployments page.

## 2. Connect the GitHub repository to Vercel

1. In Vercel, select the SASTRAVA team and choose **Add New → Project → Import Git Repository**.
2. Select `SASTRAVA/FINESSE` and grant the Vercel GitHub App access to that repository if prompted.
3. Set **Root Directory** to `.` (repository root). Keep the root directory setting unchanged for all environments.
4. Use these build settings, which are versioned in `vercel.json`:
   - Framework preset: **Other** / no framework preset override.
   - Build command: `cd frontend && npm ci && npm run build`.
   - Output directory: `engine/web/react-ui`.
   - Install command: leave automatic/default; the build command installs the frontend lockfile with `npm ci`.
   - Python Function entrypoint: `api/index.py`; it exports `engine.main:app` as the ASGI application.
   - Function include glob: `{engine,migrations}/**` so the Python package and SQL migrations are present in the deployed function.
5. Keep `vercel.json` as the source of truth for rewrites and security headers. `/api/*`, `/hubapi/*`, `/workspace`, `/`, and the dashboard routes are rewritten to `api/index.py`.
6. Select the `main` production branch. Keep automatic Git deployments enabled. Do not create a second project if the existing FINESSE project is still linked to `SASTRAVA/FINESSE`; verify the project ID and Git connection first.

Vercel manages the Python runtime for the root `api/` function and installs root `requirements.txt`. Set function memory and maximum duration in Project Settings to values available on the account plan and compatible with the function workload. The repository does not claim long-running worker support on Vercel; durable/background jobs belong in a separately provisioned worker service.

## 3. Set production environment variables

Add each value to **Project → Settings → Environment Variables**, select **Production** (and Preview separately only if appropriate), save, and redeploy. Do not put secrets in Git, issue comments, deployment URLs, or this runbook.

| Variable | Production setting |
|---|---|
| `ENVIRONMENT` or `FINESSE_ENV` | `production` (Vercel also sets `VERCEL_ENV=production`) |
| `JWT_SECRET` | Unique random value, at least 32 bytes; use `openssl rand -hex 32` |
| `JWT_ALGORITHM` | `HS256` only |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` by default; accepted range is 1–10080 |
| `CEO_EMAIL` or `CEO_USERNAME` | Initial administrator email/login |
| `CEO_PASSWORD` | Unique password, 12–72 UTF-8 bytes; set only as a secret |
| `KMS_MASTER_KEY` or `MASTER_KEY` | Unique random value, at least 32 bytes; use `openssl rand -hex 32` |
| `KMS_KEY_ID` | Stable active key ID, for example `primary-2026-01` |
| `KMS_KEYRING` | Optional JSON object containing previous key IDs and their key material during rotation; keep old keys until all records are rotated and old backups expire |
| `DATABASE_URL` | PostgreSQL 16+ TLS connection URL using a dedicated `NOSUPERUSER NOBYPASSRLS` application role |
| `REDIS_URL` | Reachable Redis 7 URL; required for production distributed nonce and event state |
| `QDRANT_URL` | Reachable remote Qdrant cluster URL; production does not use ephemeral in-memory vectors |
| `QDRANT_API_KEY` | Qdrant API key when the cluster requires authentication |
| `ALLOW_CONFIDENTIAL_EXTERNAL_EGRESS` | `false` unless a separately reviewed policy authorizes it |
| `REDACT_PII_ON_EXTERNAL_LLM` | `true` |
| `SALES_DRY_RUN` | `true` |
| `SALES_LIVE_OUTREACH_ENABLED` | `false` |
| `EMAIL_LIVE_ENABLED` | `false` |
| `VOICE_LIVE_ENABLED` | `false` |
| `SALES_ENRICHMENT_ENABLED` | `false` unless an approved provider and policy are configured |
| `CALENDAR_SYNC_ENABLED` | `false` unless an approved provider and policy are configured |
| `TRUSTED_PROXY_IPS` | Comma-separated trusted proxy IP addresses only when the app is bound publicly behind a trusted proxy; never trust arbitrary forwarded headers |
| `OTEL_ENABLED` | `false` unless an OTLP endpoint is configured |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional OTLP/HTTP trace endpoint when telemetry is enabled |

The app refuses to report production setup-ready when PostgreSQL, Redis, or remote Qdrant configuration is absent. Startup applies `migrations/001_multi_tenant_rls.sql`, verifies the role cannot bypass RLS or be a superuser, and checks all 24 tenant tables have enabled and forced RLS plus the tenant policy. Configure the database role and network access before the first production request. Never initialize production using a database owner/superuser account.

For key rotation, set the old key in `KMS_KEYRING` under its previous `kid`, set the new `KMS_MASTER_KEY` and `KMS_KEY_ID`, deploy, and re-encrypt tenant credentials using `TenantSecretStore.rotate_tenant(tenant_id)`. Verify every tenant has been rotated and all backups containing old envelopes have expired before removing the old key.

## 4. New deployment and smoke checks

After the GitHub push or Vercel import, wait for the new deployment to show **Ready** and confirm it was built from the expected `main` commit. Use the assigned deployment URL below as `DEPLOYMENT_URL`:

```bash
export DEPLOYMENT_URL="https://<deployment-host>.vercel.app"
curl -fsS "$DEPLOYMENT_URL/health"
curl -fsS "$DEPLOYMENT_URL/api/health"
curl -fsS "$DEPLOYMENT_URL/api/v1/platform/runtime"
curl -fsS -o /dev/null -w "%{http_code}\n" "$DEPLOYMENT_URL/"
curl -fsS -o /dev/null -w "%{http_code}\n" "$DEPLOYMENT_URL/workspace"
```

Expected results: `/health` returns 200 with `status=online`; `/api/health` returns 200 with `ok=true`; runtime reports `setup_ready=true`; `/` and `/workspace` return 200. An unauthenticated 401 on protected APIs is expected. A 503 from `/api/health` reports missing production environment variables; a failed function/build or startup indicates the Vercel logs should be checked before retrying.

Then verify automatic deployments: push a harmless reviewed commit to `main`, confirm a Vercel deployment starts for that exact Git SHA, and confirm its production alias points at the new Ready deployment. Do not infer hook health from a manually created deployment.

## 5. Operational boundaries

`/tmp`, SQLite, in-process Redis fallbacks and local vector memory are for local or test runs. Vercel function instances are ephemeral and can run concurrently, so production records, one-time approvals, broadcasts, and vectors must use the external services above. The local 15-suite script and existing unit tests do not prove live PostgreSQL, Redis, Qdrant, Vercel credentials, or account-level deployment settings; verify those directly in the target environment.
