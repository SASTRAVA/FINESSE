# Database migration safety

FINESSE currently applies ordered SQL files from `migrations/` on startup after
checking the PostgreSQL role and forced tenant RLS policies. This is not yet an
Alembic expand/contract framework.

For schema changes that may take locks, use an expand/backfill/switch/contract
sequence: add compatible nullable structures first, backfill in bounded batches,
deploy code that supports both schemas, switch reads/writes, and only remove old
structures in a separately reviewed contract migration. Production destructive
DDL must wait until the Alembic safety checker, lock/statement timeout policy,
and live PostgreSQL validation are available. Do not claim zero downtime from
SQLite or source inspection alone.
