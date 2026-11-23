# RLS or model-egress anomaly containment

1. Treat any cross-tenant retrieval or unexpected provider request as a
   severity-one security event. Record time, request ID, tenant, route, model,
   and evidence location without copying sensitive payloads into chat or logs.
2. An L4 operator can set `cloud_llm_egress_enabled` false with
   `PUT /api/v1/admin/kill-switches/cloud_llm_egress_enabled`. Verify the API
   response and a subsequent local provider decision. This switch is stored in
   the configured platform database; propagation across replicas is not yet
   guaranteed without distributed invalidation.
3. Pause affected ingestion/retrieval or tenant access through the deployment
   control plane. Revoke affected user sessions and connector tokens. Do not
   delete evidence or run a broad purge before preservation and impact review.
4. Check route authorization inventory, tenant context binding in
   `engine/db/storage.py`, and Qdrant filters in `engine/rag/store.py` and
   `engine/rag/retriever.py`. Reproduce only with synthetic tenant fixtures.
5. Restore traffic only after a reviewed fix, focused regression tests, and
   accountable security-owner approval. Run the tenant isolation and egress
   tests before re-enabling cloud traffic.

Live Postgres/Qdrant pool isolation and cross-replica switch propagation remain
deployment tests and are not implied by local test results.
