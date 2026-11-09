# Deploy FINESSE to Vercel

FINESSE is deployed as a Vite React workspace served by a FastAPI ASGI function. `vercel.json` builds the frontend into `engine/web/react-ui`, includes the Python `engine/` package in the function bundle, and rewrites API and workspace routes to `api/index.py`.

## Required project configuration

Link this checkout to the intended Vercel project, then configure its environment variables from `.env.example`. Set a unique random `JWT_SECRET` (at least 32 characters) and the initial administrator credentials. Configure a managed PostgreSQL `DATABASE_URL` for durable tenant records and a managed Redis `REDIS_URL` for shared rate limiting when those services are enabled. Keep optional integrations disabled until their credentials, consent controls, and production procedures have been reviewed.

The default sales configuration is dry-run. Email, voice, enrichment, and calendar integrations are gated by explicit feature flags. Never use local SQLite or Vercel's function filesystem as the durable production store; serverless filesystems and process memory are not shared persistent infrastructure.

## Deploy

From an authenticated machine with the project linked:

```bash
vercel deploy          # Preview deployment
vercel deploy --prod   # Production deployment
```

The Vercel project `finesse` is connected to `SASTRAVA/FINESSE` and owns `finesse-psi.vercel.app`. This workspace copy has no local `.git` remote or `.vercel` link. Push changes to a branch in the connected GitHub repository to trigger a Preview deployment; use the reviewed production branch flow for live releases.

## Verify a deployment

Check the UI and service endpoints:

```text
/
/api/health
/api/v1/platform/runtime
/api/v1/openapi
```

Review Vercel function logs and configured environment variables after deployment. Protected `/api/v1/*` resources require an authenticated token; an unauthenticated `401` response is expected for protected routes.

## Current implementation boundary

This repository includes the FastAPI/React application, role and tenant foundations, PostgreSQL-aware storage and migrations, Redis-backed rate-limiting support, Qdrant retrieval, and guarded automation modules. The upstream project describes itself as prototype/development software; passing local checks does not establish production hardening, operational readiness, or regulatory compliance. See [PROJECT_REPORT.md](PROJECT_REPORT.md) and [SECURITY.md](SECURITY.md) before exposing it to real users or data.
