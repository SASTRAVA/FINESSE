# Incident and breach response

1. Open an incident record with `POST /api/v1/compliance/breach-incidents` as
   an authorized L4 operator. Record discovery time, scope, containment, and
   known affected data; do not put secrets or raw personal data in free-text
   fields.
2. Preserve relevant request IDs, audit-chain evidence, deployment identifiers,
   and provider logs under the approved incident evidence process. Restrict
   access to the incident record.
3. Contain the active path: disable cloud egress or the affected feature with
   `PUT /api/v1/admin/kill-switches/{flag_key}` where applicable; revoke
   compromised sessions/tokens; isolate affected credentials and hosts.
4. Notify the incident commander and privacy/legal owner immediately. They
   decide affected-person and regulator notifications using applicable law,
   contracts, jurisdiction, and confirmed facts. The software's 72-hour field
   is a tracking deadline, not a legal determination or notification service.
5. Update containment, notification, root-cause, and remediation evidence in the
   incident record. Do not close until owners accept residual risk and evidence
   is preserved.

No notification transport, statutory applicability engine, or paging worker is
currently deployed. Use the organization's approved incident process.
