# Database PITR and Qdrant recovery

1. Declare a maintenance incident and stop writes through the deployment
   control plane. Preserve current database and vector-store snapshots before
   attempting recovery.
2. For portable SQLite, stop the Compose stack with the safe-stop script and
   use the timestamped integrity-checked backup bundle. Run `PRAGMA
   integrity_check` on a copy before restoring it. Never overwrite the only
   backup or restore over a running database.
3. For PostgreSQL, use the database operator's configured point-in-time recovery
   procedure and a new isolated recovery instance. This repository does not
   configure pgBackRest, WAL archiving, or a restore target.
4. Restore Qdrant from the provider's consistent snapshot into an isolated
   collection/cluster. Verify collection schema, payload indexes, tenant/lane/
   sensitivity filters, and point counts using synthetic tenants.
5. Reconcile relational document versions against vector payload versions,
   run migration and tenant-isolation contracts, then direct traffic only after
   application and data owners approve the recovered point.

No production PITR or Qdrant restore drill has been run. Do not treat an SQLite
backup bundle as a PostgreSQL or remote-Qdrant backup.
