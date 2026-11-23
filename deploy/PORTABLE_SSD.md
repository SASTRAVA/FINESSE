# FINESSE portable SSD server

This profile runs FINESSE as a local container server with state kept in the
`portable-runtime/` directory beside the repository. It uses SQLite with WAL,
embedded Qdrant, hash embeddings, and a local Ollama service. The default
runtime Docker network is internal-only; the API is published on the host's
loopback address and Ollama is not published to the host network.

This is a Docker-based local server, not a bootable OS or a hardware-encrypted
SSD. The computer still needs Docker Engine with Compose. Docker stores its
container layers and host logs in the Docker host's own storage. FINESSE data,
vault files, and Ollama models are bind-mounted to `portable-runtime/` on the
drive. Use an encrypted SSD and host OS controls for physical protection.

## First-time setup while connected

1. Copy the repository to the SSD, connect it to a host with rootless Docker
   Engine and the Compose plugin, and open a terminal at the repository root.
2. Copy `.env.portable.example` to `.env.portable` and fill its required blank
   values. Generate `JWT_SECRET` and `KMS_MASTER_KEY` independently with
   `python -c "import secrets; print(secrets.token_hex(32))"`. Set a unique
   `CEO_PASSWORD` of 12–72 bytes. Keep `.env.portable` private; it is ignored by
   Git.
3. Build and cache the application and Ollama images while online:

   ```powershell
   docker compose --env-file .env.portable -f deploy/compose.portable.yaml build api
   docker compose --env-file .env.portable -f deploy/compose.portable.yaml pull ollama
   ```

4. Provision the local model. This temporary overlay gives the Ollama
   container outbound access, starts only Ollama, and leaves the FINESSE API
   stopped. Model files are written to `portable-runtime/ollama` on the SSD.

   ```powershell
   docker compose --env-file .env.portable -f deploy/compose.portable.yaml -f deploy/compose.portable.provision.yaml up -d ollama
   docker compose --env-file .env.portable -f deploy/compose.portable.yaml -f deploy/compose.portable.provision.yaml exec ollama ollama pull llama3.2:3b
   docker compose --env-file .env.portable -f deploy/compose.portable.yaml -f deploy/compose.portable.provision.yaml down
   ```

   If `.env.portable` selects another `LOCAL_LLM_MODEL`, use that same model
   name in the `ollama pull` command.
5. For a different computer, save the images on the SSD and load them into that
   computer's Docker Engine before going offline:

   ```powershell
   New-Item -ItemType Directory -Force portable-runtime\images | Out-Null
   docker save -o portable-runtime\images\finesse-images.tar finesse-portable:local ollama/ollama:0.40.17
   # On the destination computer:
   docker load -i portable-runtime\images\finesse-images.tar
   ```

## Start and verify

Run from the repository root after connecting the SSD:

```powershell
docker compose --env-file .env.portable -f deploy/compose.portable.yaml config --quiet
docker compose --env-file .env.portable -f deploy/compose.portable.yaml up --no-build -d
docker compose --env-file .env.portable -f deploy/compose.portable.yaml ps
Invoke-RestMethod http://127.0.0.1:8600/health
Invoke-RestMethod http://127.0.0.1:8600/api/health
```

On Windows, `scripts/finesse-start.ps1` validates Compose, starts the stack,
waits for `/readyz`, and opens the workspace. Stop with
`scripts/finesse-stop.ps1`; it waits for active jobs and checkpoints/backups
SQLite before reporting that the stack stopped.

On Linux/macOS, use `bash scripts/finesse-start.sh` and
`bash scripts/finesse-stop.sh`. Safe stop waits for active work, stops the
Compose services, checkpoints SQLite, verifies a SQLite backup, and writes a
hashed bundle containing the database snapshot, local Qdrant files, and vault
archive. Keep the source SSD connected until the scripts complete.

Change `FINESSE_PORT` in `.env.portable` when port 8600 is already in use, then
use that port for both health checks. Confirm both services report healthy,
sign in through the local workspace, and make one non-sensitive local-model
request. The API route should be reachable at `127.0.0.1` only. The Ollama
service has no published host port.

To stop the server, wait for active work to finish and run:

```powershell
docker compose --env-file .env.portable -f deploy/compose.portable.yaml down
```

Wait until the API container exits before unplugging the drive. Back up
`portable-runtime/data`, `portable-runtime/vault`, `portable-runtime/ollama`,
and `.env.portable` to a separate encrypted drive. The env file contains
authentication and encryption keys; protect it separately from the database.

## Source-to-repository implementation map

| Supplied source requirement | Repository implementation | State / boundary |
| --- | --- | --- |
| Portable paths bound to the drive | `deploy/compose.portable.yaml` bind-mounts `portable-runtime/data` and `portable-runtime/vault`; `FINESSE_DATA_DIR` and `VAULT_PATH` point inside the container to those mounts. | Implemented for application data and vault. Docker Engine image layers and logs remain host-managed. |
| Local inference with no required cloud API | The portable profile routes `LOCAL_LLM_BASE_URL` to the Ollama container and persists its model directory on the SSD. | Implemented after the model is staged; provisioning requires internet once. |
| Embedded database and local vectors | SQLite WAL from `engine/db/storage.py`; embedded Qdrant at `/app/data/qdrant`. | Implemented for one local server instance. |
| Offline operation and blocked egress | Compose `isolated` network is `internal: true`; cloud keys, telemetry, crawlers, harvesters, and live provider effects are disabled. | Container egress is isolated at runtime. Docker image/model staging and host software updates require a connected setup phase. |
| Reduce flash writes and recover from interrupted writes | SQLite WAL with `synchronous=FULL`; container `/tmp` is a RAM-backed tmpfs. | Implemented in software; abrupt physical removal can still interrupt writes and is not a substitute for drive testing or backups. |
| Bound local model memory pressure | Portable Compose caps FINESSE local inference concurrency at 2 and Ollama parallel requests at 2 with one loaded model by default. | Software defaults only; tune and measure on the selected GPU/CPU and model. |
| Encrypted SSD, physical PIN/FIDO unlock, rugged enclosure | No hardware control code in this repository. | Requires purchase/configuration of a compatible encrypted drive and validation by its vendor. |
| Bootable hardened live OS and zero host traces | The portable server runs under the host's Docker Engine. | Not implemented. Requires a separate bootable Linux image and hardware/firmware validation; Docker also uses host-managed storage and logs. |
| Automatic paired-drive incremental backup | The runbook documents a stopped-service backup set. | Manual backup only; automatic dual-drive sync and restore testing remain future work. |
| USB throughput and AI tokens/second targets | No benchmark harness or attached target hardware. | Not verified; must be measured on the selected SSD and host CPU/GPU. |

The supplied PRD and architecture plan describe a proposed hardware product.
This profile implements the repository-level portable server foundation and
does not certify the hardware edition or satisfy regulatory requirements.
