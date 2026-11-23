# Portable SSD field operations and WAL recovery

1. Unlock and mount the encrypted drive using its vendor procedure. Confirm the
   expected drive identity and filesystem before starting FINESSE. This repo
   cannot verify hardware encryption or mount identity.
2. Copy `.env.portable.example` to `.env.portable`, set unique random JWT/KMS
   values, and configure a signed license if the distributor requires it.
   Keep secrets and `license.json` in the protected data volume, not Git.
3. Run `scripts/finesse-start.ps1` on Windows or `scripts/finesse-start.sh` on
   POSIX. Confirm `/readyz` returns ready and open the workspace at loopback.
   Offline model images must have been provisioned before the engagement.
4. Before disconnecting, wait for active jobs to finish, then run the matching
   `scripts/finesse-stop.*` wrapper. It refuses active jobs, stops containers,
   checkpoints SQLite, verifies a backup, and bundles SQLite/Qdrant/vault data.
   Wait for the script to finish and all containers to stop before ejecting.
5. If startup reports SQLite integrity errors, do not run `VACUUM` or overwrite
   the database. Preserve the original drive, clone it if possible, and restore
   the newest verified backup to a separate copy for inspection.

The scripts do not trigger a hardware lock, zero host traces, auto-unmount the
drive, or validate recovery after physical power loss.
