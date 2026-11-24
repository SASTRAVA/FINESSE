# FINESSE Frontend Pages and Deployment Report

**Audit date:** 2026-11-24
**Last pushed revision inspected:** `8443e847810a0c80145a51aee2d4bfaa7de25da6` (`main`)
**Production URL checked:** <https://finesse-theta.vercel.app/>

## Deployment finding

The Vercel project is connected to `SASTRAVA/FINESSE` and deploys `main`. Its
previous deployment served the React site but returned 404 for the backend API.
The Vercel project was set to the **Other** framework with a static output
directory, so requests were not routed through the FastAPI app.

The Vite public base is `/`. The FastAPI app serves the React workspace at the
website root on Vercel and at `/workspace`; its `/assets` mount serves the
compiled JavaScript and CSS. Vercel must use the FastAPI framework preset and
must not force a static output directory, so the same deployment routes
`/api/*` requests into the app.

The previous static deployment served the corrected HTML and assets, but its
API paths returned 404. The current code change routes these through FastAPI;
production verification is pending the Vercel deployment with the FastAPI
framework preset.

The Vercel project currently has the authentication variables, but the
production encryption key, PostgreSQL, Redis, and Qdrant settings are not
configured. The API can be routed on the same origin, but it will report
`setup_ready=false` and `/api/health` will report setup requirements until
those dependencies are provisioned. Same-origin `VITE_API_BASE_URL` and
`VITE_WS_BASE_URL` stay blank; never place secrets in `VITE_*` variables.

The current live site confirms the old deployment gap: requests to
`/api/v1/platform/runtime` and `/api/health` return 404. The next deployment
must route them to FastAPI; after routing, missing production dependencies
should be reported as structured setup status rather than a 404.

## Pages available in the React workspace

The React app is a single-page application, not a route-per-screen application.
It has a sign-in/MFA screen and five in-app sections. These are the actual
front-end screens implemented in `frontend/src/workspace.tsx`:

| Screen | What it displays | Main API use |
|---|---|---|
| Sign in / MFA | Email, tenant, password; MFA challenge and enrollment setup when required | `POST /api/v1/auth/login`, `POST /api/auth/mfa/enroll`, `POST /api/auth/mfa/verify` |
| Command | Review-only directive planning, system overview, service catalog | `POST /api/v1/orchestra/conjunction`; `GET /api/command/overview`, `/api/v1/services` |
| Sales | Synthetic lead generation, consent record, email draft/send, voice call request, enrichment, encrypted provider-secret entry, and sales data cards | `GET /api/v1/leads`, `/api/v1/campaigns`, `/api/v1/email/messages`; `POST /api/v1/leads/generate`, `/api/v1/privacy/consent`, `/api/v1/email/generate`, `/api/v1/email/send`, `/api/v1/voice/calls`, `/api/v1/leads/{id}/enrich`; `PUT /api/v1/settings/provider-secrets` |
| Memory & tools | Human-confirmed pattern save plus permitted MCP and registered security tool data cards | `GET /api/v1/memory/patterns`, `/api/tools`, `/api/v1/security/tools`; `POST /api/v1/memory/patterns` |
| Security & catalog | Emergency stop, review-only repository evidence evaluation, catalog, security tool and audit data cards | `GET /api/v1/catalog/repositories`, `/api/v1/security/tools`, `/api/v1/audit-logs`; `POST /api/v1/admin/emergency-stop`, `/api/v1/catalog/repositories/certify` |
| Calendar | Meeting and availability data plus local ICS invite creation; external sync is separately opt-in | `GET /api/v1/calendar/meetings`, `/api/v1/calendar/slots`; `POST /api/v1/calendar/meetings` |

The five sections are buttons that change React state. They do not have separate
route state. The path does not select the section: opening `/workspace/sales`,
for example, still starts on Command. Sign-in is the first screen until a
session token exists; MFA is a conditional step rather than another URL.

## URL and legacy page inventory

| URL / alias | Local FastAPI behavior | Vercel with FastAPI preset |
|---|---|---|
| `/` | Serves the JARVIS page (`engine/web/jarvis.html`) | Serves the React workspace entry document |
| `/workspace` and `/workspace/*` | Serves the built React SPA | Served by FastAPI static mount |
| `/dashboard`, `/universe` | Serves `engine/web/dashboard.html` | Redirects to `/workspace/overview` |
| `/innovation` | Serves `engine/web/innovation.html` | Served by FastAPI route |
| `/jarvis`, `/voice` | Both serve `engine/web/jarvis.html` | Redirects to `/workspace/jarvis` |
| `/command` | Serves `engine/web/command.html` | Redirects to `/workspace/command` |
| `/hub` | Serves the bundled hub at `engine/web/hub` when present | Served by FastAPI static mount when present |
| `/api/*` | FastAPI endpoints | Same-origin FastAPI endpoints |

On Vercel, `/workspace/overview`, `/workspace/command`,
`/workspace/jarvis`, and `/workspace/voice` are URL aliases to the same React
entry and all initially show the Command section after sign-in. The workspace's
“Classic dashboard” and “Command dashboard” links lead to the configured
workspace aliases. The local FastAPI pages remain available in local/server
deployments; Vercel redirects their legacy names into the React workspace.

## Frontend display architecture

```text
Browser
  └─ Vercel FastAPI app (app.py → engine.main:app)
       ├─ / → React workspace document
       ├─ /assets/* and /workspace/* → built React files
       ├─ /api/*, /health, /readyz → FastAPI routes
       └─ legacy aliases → /workspace/*
            └─ frontend/src/main.tsx
                 ├─ React 19 createRoot + StrictMode
                 ├─ frontend/src/workspace.tsx
                 │    ├─ Sign in / MFA state
                 │    ├─ Command | Sales | Memory & tools
                 │    └─ Security & catalog | Calendar
                 ├─ frontend/src/style.css (responsive dark workspace)
                 └─ frontend/src/api/client.ts
                      ├─ VITE_API_BASE_URL → blank for same-origin API
                      └─ VITE_WS_BASE_URL → blank for same-origin WebSocket
```

The workspace stores the bearer session token in tab-scoped `sessionStorage`,
uses authenticated JSON fetches for data and actions, and clears the token when
the API reports that MFA is required. Failed data requests are represented as
unavailable data/errors. A short-lived-ticket WebSocket URL helper exists, but
the current workspace component does not establish a live WebSocket connection.
The provider-secret form uses `PUT`, matching the API's update route; the other
workspace forms use `POST`. Styling is supplied by `frontend/src/style.css`,
including a narrow-screen layout and reduced-motion support. Calendar inputs
accept browser-local `datetime-local` values and convert them to ISO timestamps;
their labels explicitly say “your local time.”

Vercel's project framework preset must be FastAPI so the ASGI app, rather than
only its static assets, handles requests. The project must also have PostgreSQL,
Redis, Qdrant, KMS, and authentication settings before the API reports ready.

## Verification scope and remaining work

The remote dashboard confirmed repository linkage and a Ready deployment. The
public frontend and assets are live, but backend routes remain 404 until the
FastAPI preset deployment completes. The production resources listed above are
also required before the backend can report ready.
