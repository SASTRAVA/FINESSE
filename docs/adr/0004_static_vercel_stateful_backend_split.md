# ADR 0004: Static Vercel frontend and separate stateful API

- **Status:** Accepted.
- **Decision:** Vercel builds and serves only the React SPA. FastAPI, WebSockets, persistent databases, workers, and secrets belong on a separately operated stateful backend. The frontend receives public API and WebSocket base URLs at build time.
- **Reason:** Serverless frontend hosting does not provide the persistence, long-running agent work, or sustained WebSocket lifecycle required by FINESSE.
- **Consequences:** API hosting, TLS, origins, CORS, WebSocket availability, and secrets must be configured at the backend. No backend cloud resource is provisioned by the static Vercel project.
- **Evidence:** `vercel.json`, frontend API client, and Vercel deployment tests.
