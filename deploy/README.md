# Rootless deployment and operations

## Data flow and trust boundaries

```text
Browser --TLS--> reverse proxy --trusted client/proto headers--> API
                                                       |-- PostgreSQL (transaction-local tenant RLS)
                                                       |-- Redis (shared login throttle)
                                                       |-- local vault/data volumes
                                                       |-- optional provider endpoints (off by default)
Security worker --authorized dry-run plans--> human review queue
```

The API binds inside the container to `0.0.0.0`; Compose publishes only
`127.0.0.1:8600` on the host. Put a TLS reverse proxy in front of it and set
`TRUSTED_PROXY_IPS` to the exact address the API sees for that proxy. Do not
trust forwarded headers from other peers. Production startup refuses the
non-loopback API bind if no trusted proxy is configured; the
`ALLOW_UNENCRYPTED_PUBLIC_BIND` override is not recommended.

The Postgres and Redis services are internal-only and have no published ports.
PostgreSQL RLS is enforced on the application's tenant tables; use a dedicated
non-superuser database role without `BYPASSRLS`. Redis stores hashed account
keys and login throttle state, not provider credentials. Secrets set through
the tenant provider-secret API are AES-GCM encrypted with a separately managed
`KMS_MASTER_KEY`. Database backups do not replace a protected backup of that
key.

Live email, voice, enrichment, and calendar providers remain disabled in the
Compose environment. The security worker is review-only and does not invoke
scanner binaries or run arbitrary commands.

## Prerequisites and configuration

- Rootless Docker Engine with the Compose plugin.
- A TLS-terminating reverse proxy with a stable container-network address.
- A protected `.env` file, created from `.env.example`; never commit it.

Set unique high-entropy values for `JWT_SECRET`, `CEO_PASSWORD`,
`POSTGRES_PASSWORD`, `WEBHOOK_SIGNING_SECRET`, and `KMS_MASTER_KEY`. Set
`TRUSTED_PROXY_IPS` to the proxy's exact source address; do not use wildcards
or an entire untrusted network. `CORS_ORIGINS` should list only the frontend
origins served by the proxy. Keep all sales/provider live flags disabled until
the corresponding provider, legal basis, consent process, and operational
monitoring are reviewed.

## Deploy and verify

From the repository root:

```sh
docker compose --env-file .env -f deploy/compose.yaml config
docker compose --env-file .env -f deploy/compose.yaml up --build -d
docker compose --env-file .env -f deploy/compose.yaml ps
curl --fail http://127.0.0.1:8600/health
```

The health response means the API process is serving. It is not a guarantee
that model providers or optional sales providers are available. Verify
`/workspace/`, authenticate, check the tenant boundary, and confirm that email
and voice endpoints remain dry-run. Never probe an actual prospect or start a
real call as a health check.

## Upgrade, backup, and rollback

1. Record the deployed image/source revision and take a database snapshot.
2. Back up the vault/data volumes and the KMS master key separately using the
   organization's encrypted backup service.
3. Review and apply any SQL migration using a deployment identity with
   migration rights; the API role remains non-superuser and `NOBYPASSRLS`.
4. Deploy the new image, verify `/health`, authenticated login, and a
   non-destructive tenant read.
5. If verification fails, restore the previous image and compatible database
   snapshot. Do not roll back a database schema without the matching snapshot.
6. Rotate any credentials that may have been exposed; do not place secret
   values in command history, tickets, or logs.

Do not run scanners from the worker. It transitions authorized scan plans to
`DRY_RUN_REVIEW_REQUIRED`; execution remains an independent, human-controlled
process.
