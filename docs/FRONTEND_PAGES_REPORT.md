# FINESSE Frontend Pages and Deployment Report

**Audit date:** 2026-11-24
**Pre-fix revision inspected:** `8193062ac309ec9cbefbf48a1e91b98eb593ef65` (`main`)
**Fix pushed to:** `4322fef6e2b1c4accf43e4f7cf617a609121e5fa` (`main`)
**Production URL checked:** <https://finesse-theta.vercel.app/>

## Deployment finding

The Vercel project is connected to `SASTRAVA/FINESSE`, and its dashboard showed
the `main` deployment for the inspected revision as Ready. The deployed site
nevertheless rendered a blank white page. The production HTML requested its
JavaScript and CSS from `/workspace/assets/...`; the build output stores those
files at `/assets/...`. Vercel's `/workspace/:path*` rewrite consequently
returned the HTML document for the JavaScript request. The browser could not
start the React app.

The Vite public base is now `/`, matching the configured output directory
(`engine/web/react-ui`) at the domain root. The `/workspace` SPA rewrites remain
for direct workspace URLs. FastAPI also serves the generated `/assets` folder
at the root so the same bundle remains usable at `/workspace/` in local/server
deployments. This corrects the observed blank-page cause.

After the push, the production root serves the corrected HTML, the new JavaScript
bundle (`/assets/index-DemWlrd4.js`) returns HTTP 200 with a JavaScript content
type, and the CSS bundle returns HTTP 200 with a CSS content type. Direct
`/workspace/overview` also returns the SPA document. These checks confirm the
assets needed to render the React page are available at the deployed URLs.

Vercel serves the frontend as static files. The FastAPI service, database,
Redis, Qdrant, and their secrets are not provisioned by this static site. Set
the public build-time `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` to the
separately hosted API and WebSocket origins. Until that backend is configured
and reachable, the page can render but sign-in, runtime status, data loading,
and workspace actions cannot work. Do not put backend credentials in `VITE_*`
variables.

The current live site confirms this remaining configuration gap: requests to
`/api/v1/platform/runtime`, `/api/health`, and `/api/v1/auth/login` return 404
responses from the static deployment. The sign-in form consequently reports
that it did not receive JSON. The frontend now explains that the backend URL
must be configured instead of showing only a generic parsing error.

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

| URL / alias | Local FastAPI behavior | Current static Vercel behavior |
|---|---|---|
| `/` | Serves the JARVIS page (`engine/web/jarvis.html`) | Serves the React workspace entry document |
| `/workspace` and `/workspace/*` | Serves the built React SPA | Rewrites to the SPA entry document |
| `/dashboard`, `/universe` | Serves `engine/web/dashboard.html` | Redirects to `/workspace/overview` |
| `/innovation` | Serves `engine/web/innovation.html` | No Vercel mapping; the static output contains only the React workspace |
| `/jarvis`, `/voice` | Both serve `engine/web/jarvis.html` | Redirects to `/workspace/jarvis` |
| `/command` | Serves `engine/web/command.html` | Redirects to `/workspace/command` |
| `/hub` | Serves the bundled hub at `engine/web/hub` when present | Not included in the configured React output |

In the static Vercel app, `/workspace/overview`, `/workspace/command`,
`/workspace/jarvis`, and `/workspace/voice` are URL aliases to the same React
entry and all initially show the Command section after sign-in. The workspace's
“Classic dashboard” and “Command dashboard” links do not open the standalone
FastAPI pages on this static deployment: `/` is the React app and `/command`
redirects back into it. The legacy pages remain available when the FastAPI app
is run locally or is hosted with its static assets.

## Frontend display architecture

```text
Browser
  └─ Vercel static site (engine/web/react-ui)
       ├─ index.html → /assets/*.js + /assets/*.css
       ├─ /workspace/* → index.html (SPA fallback)
       └─ legacy Vercel aliases → /workspace/*
            └─ frontend/src/main.tsx
                 ├─ React 19 createRoot + StrictMode
                 ├─ frontend/src/workspace.tsx
                 │    ├─ Sign in / MFA state
                 │    ├─ Command | Sales | Memory & tools
                 │    └─ Security & catalog | Calendar
                 ├─ frontend/src/style.css (responsive dark workspace)
                 └─ frontend/src/api/client.ts
                      ├─ VITE_API_BASE_URL → HTTPS API origin
                      └─ VITE_WS_BASE_URL → WSS event origin
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

The local FastAPI application additionally serves the standalone JARVIS,
dashboard, innovation, command, and optional Hub surfaces. Those server-rendered
HTML pages are a separate frontend family; they are not emitted into the
configured Vercel static output directory.

## Verification scope and remaining work

The remote dashboard confirmed repository linkage and a Ready deployment. The
public URL rendered blank before the asset-base fix; after the push, its HTML
and both compiled assets returned successful responses. The external backend
origin and its runtime configuration were not verified as part of this static
frontend correction. The React workspace is renderable independently of that
service, but its authenticated features need the separately hosted API and
WebSocket services described above.
