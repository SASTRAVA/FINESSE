#!/usr/bin/env bash
set -euo pipefail
env_file="${1:-.env.portable}"
python scripts/portable_safe_stop.py --env-file "$env_file" \
  --data-dir "${FINESSE_DATA_DIR:-portable-runtime/data}" \
  --vault-dir "${VAULT_PATH:-portable-runtime/vault}" \
  --wait-seconds "${FINESSE_STOP_WAIT_SECONDS:-300}"
