# P11 handoff: frontend, API client, and streaming

- Existing React 19 workspace builds in strict TypeScript mode and retains the login token in `sessionStorage` rather than localStorage.
- Added `apiUrl` and short-lived-ticket WebSocket URL helpers configured by `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` for separately hosted frontend/backend deployments.
- Remaining: generated typed OpenAPI SDK and drift guard, OIDC/MFA auth provider consolidation, reconnecting ticket WebSocket, migration of all legacy dashboard controls into routes, backend run cancellation, accessibility/mobility review, and Playwright end-to-end suite.
- Vercel now deploys only the static React SPA. Set `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` at build time to connect it to a separately deployed stateful backend; see P14 handoff.
