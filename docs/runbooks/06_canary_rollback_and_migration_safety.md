# Canary rollback and migration safety

1. Before deployment, record the prior image digest, application revision,
   migration set, and backup/snapshot identifiers. Confirm rollback compatibility
   with the expanded schema; never rely on destructive downgrade scripts.
2. Deploy to an isolated canary and monitor readiness, error rates, latency,
   audit-chain verification, and tenant-bound request tests. Define abort
   thresholds before rollout.
3. If thresholds fail, stop promotion and route traffic back to the last known
   good image using the platform's release controls. Keep additive schema
   changes in place unless the database owner has validated a safe reversal.
4. Verify `/readyz`, login/session behavior, tenant isolation, and audit-chain
   continuity against the prior release before resuming traffic.
5. Preserve the failed image, logs, and migration evidence for review. Record
   rollback outcome and follow-up owner in the incident tracker.

FINESSE does not yet include gated canary CD, a schema rollback rehearsal, or an
Alembic expand/contract safety checker. This runbook is not evidence that a live
rollback was rehearsed.
