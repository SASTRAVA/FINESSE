# P12 handoff: commercial product surfaces

## Implemented

- DOCX deliverables include SASTRAVA/tenant branding, Listen/Shape/Deliver sections, classification header, footer, and verified citation appendix. Citations are resolved against active current-version tenant documents, lane/ACL access, and sensitivity; titles and source labels come from server records. Restricted content is blocked.
- An authenticated `POST /api/v1/exports/docx` endpoint applies L3/L4 sensitivity gates and records an audit event for every export.
- Read-only client portal snapshots are tenant-scoped, internal publishing requires explicit clearance, confidential publishing requires explicit L4 override, restricted content is blocked, access tokens are hashed at rest and expire, and portal revocation invalidates reads. Publish/revoke events enter the hash-chained audit log.
- Offline billing meter adapter uses deterministic tenant/window/metric IDs for idempotency and supports CSV export. Stripe meter adapter accepts an injected client callback and uses deterministic idempotency keys.
- Voice policy requires local providers for confidential/restricted audio and marks side-effecting voice actions as Gatekeeper-only.
- Added three forced-RLS tables for portals and billing events.

## Remaining P12 gates

- No L4 control-plane/admin React routes or audit-verification UI.
- DOCX is the only exporter; PPTX/PDF, full Markdown sanitization, white-label controls, and export API/audit controls remain.
- Portal email allowlists, viewer-specific watermarking, signed deep links/OTP, and public portal HTTP route remain.
- Stripe adapter has no account credentials or webhook handler; only offline local ledger is tested.
- There is no browser WebRTC transport or Pipecat/Silero/Whisper/Kokoro pipeline. Those models, codecs, microphone hardware, and latency tests require installation and target hardware.
