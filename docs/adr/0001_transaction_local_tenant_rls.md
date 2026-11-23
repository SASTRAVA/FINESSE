# ADR 0001: Transaction-local tenant binding for PostgreSQL RLS

- **Status:** Accepted for the PostgreSQL storage adapter; live pool stress remains unverified.
- **Decision:** Set `app.current_tenant_id` with transaction-local `set_config(..., true)` inside the tenant-scoped transaction, and require forced RLS policies as a second boundary.
- **Reason:** Connection-pool reuse must not carry one request's tenant context into another transaction.
- **Consequences:** Every tenant-sensitive query must run within the storage transaction API. Tests and migrations must preserve forced RLS and validate rollback/exception cleanup. SQLite tests do not prove PostgreSQL semantics.
- **Evidence:** `engine/db/storage.py`, ordered SQL migrations, and production contract suite.
