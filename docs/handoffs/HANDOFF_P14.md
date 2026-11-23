# P14 handoff: deployment infrastructure

- Existing Docker Compose and Dockerfile use non-root runtime, read-only root filesystems, dropped capabilities, and health probes; CI runs dependency and filesystem/secret scans.
- Frontend API/WS URL helpers support a separately hosted static client.
- `vercel.json` now builds and serves the static React output only, has workspace SPA rewrites and hardening headers, redirects four legacy operator pages, and no longer routes API traffic to `api/index.py`.
- Set `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` at frontend build time to the separately deployed stateful backend; those endpoints are not provisioned by this repository change.
- Terraform/OpenTofu, Helm, ECS, signed immutable image promotion, staging/canary rollback workflow, and live container builds were not completed. No cloud account or deployment credentials were used.
