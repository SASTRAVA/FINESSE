# P16 handoff: compliance and launch readiness

## Implemented

- Tenant-scoped consent grant/withdrawal and audit records.
- DSAR/grievance records with configurable workflow fields and a 90-day due-date field.
- Breach incident records include a 72-hour report deadline and containment/notification fields.
- Retention planner enforces a 365-day minimum candidate window and reports tombstone hashes; it never deletes records automatically.
- Tenant/global kill-switch records; the cloud LLM egress switch is enforced by provider selection.
- Authenticated consent grant/withdrawal and L4 incident/evidence/kill-switch API routes are available.
- Added forced-RLS coverage for incident, DSAR, and switch tables.
- Added six operational runbooks and six architecture decision records for incident response, tenant/egress containment, local inference, recovery, portable field operations, migrations, RLS, retrieval, Gatekeeper, hosting topology, portable mode, and key envelopes.
- Added `scripts/verify_production_gates.py`, which requires evidence for all 12 gates and 8 pillars, hashes repository-contained evidence files, optionally signs the report with an externally supplied Ed25519 key, and exits nonzero when any requirement or signature is missing.

## Remaining P16 gates

- These code controls do not establish legal compliance. Notice text, purposes, lawful bases, jurisdictional deadlines, retention schedules, consent-manager interoperability, DPO/SDF obligations, and data localization must be confirmed by accountable privacy/legal owners against current law and contracts.
- No automated production retention purge, consent-purpose processing halt across every subsystem, breach notification delivery, or distributed sub-second switch invalidation exists.
- No independent SOC 2/GDPR/DPDP audit, evidence bundle, rollback rehearsal, or 12-gate launch sign-off was performed.
- No verified evidence manifest or signing key was provided, so the strict verifier correctly fails and no signed readiness certificate is available. The live rollback rehearsal also remains unperformed.
- No compliance certificate or signed production approval is generated.
