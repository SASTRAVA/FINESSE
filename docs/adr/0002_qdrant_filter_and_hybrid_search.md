# ADR 0002: Mandatory Qdrant scope and optional hybrid retrieval

- **Status:** Accepted in the application query path; remote cluster behavior remains unverified.
- **Decision:** Build tenant, lane, sensitivity, active-version, and ACL filters from authenticated server context. Apply those filters to each dense and sparse retrieval branch. Use native Qdrant fusion only when the collection schema supports it; retain the bounded local lexical path as fallback.
- **Reason:** Postgres RLS does not protect vector-store points, and client-provided filters are not an authorization boundary.
- **Consequences:** Existing vector collections may require explicit migration/reindex before hybrid mode. Validate filter presence and data isolation against the production Qdrant version before rollout.
- **Evidence:** `engine/rag/store.py`, `engine/rag/retriever.py`, and security-filter tests.
