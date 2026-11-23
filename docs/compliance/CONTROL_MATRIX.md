# Compliance control evidence map

This file is an engineering evidence index, not a compliance attestation or legal
interpretation. Owners must validate control applicability, notices, lawful basis,
retention schedules, incident reporting, and customer commitments.

| Control area | Current software evidence | Remaining evidence/owner action |
| --- | --- | --- |
| Tenant separation | `engine/db/storage.py`, ordered forced-RLS migrations, route inventory | Live PostgreSQL pool/RLS tests; operations owner |
| Access and authentication | MFA, SCIM, session revocation, signing keys | IdP integration, access review, recovery drill |
| Audit and incident records | Hash-chained audit log; breach/DSAR workflows | Retention policy approval, notification process and exercise |
| Data subject requests | Tenant-scoped request and consent records | End-to-end data inventory, response/review SLA and deletion controls |
| Encryption/offboarding | Tenant DEK envelope and adapter interfaces | Production KMS/BYOK key lifecycle and restore evidence |
| Availability/recovery | SQLite backup helper; deployment health probes | PostgreSQL PITR, Qdrant restore, RTO/RPO evidence |
| Vendor and model risk | Egress policy, provider scrubbing, local routing | Vendor agreements, data residency and model validation |
| Independent assurance | CI and security regression suite | External auditor, scope, evidence period, and management sign-off |
