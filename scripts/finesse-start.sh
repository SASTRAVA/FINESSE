#!/usr/bin/env bash
set -euo pipefail

env_file="${1:-.env.portable}"
port="${FINESSE_PORT:-8600}"
compose_file="deploy/compose.portable.yaml"
[[ -f "$env_file" && -f "$compose_file" ]] || {
  echo "Portable env and Compose files must exist; copy .env.portable.example first." >&2
  exit 2
}
docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" up --no-build -d
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error "http://127.0.0.1:${port}/readyz" >/dev/null 2>&1; then
    echo "FINESSE is ready at http://127.0.0.1:${port}/workspace/"
    exit 0
  fi
  sleep 2
done
docker compose --env-file "$env_file" -f "$compose_file" ps
echo "FINESSE did not become ready within 180 seconds." >&2
exit 1
