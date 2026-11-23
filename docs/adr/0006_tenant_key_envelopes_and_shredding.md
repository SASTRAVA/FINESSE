# ADR 0006: Tenant-scoped envelope encryption

- **Status:** Accepted for the software adapter; production key custody and destruction remain unverified.
- **Decision:** Encrypt tenant secrets with AES-256-GCM data keys wrapped by an injected local or cloud KMS provider. Bind ciphertext to tenant/table/record/version as authenticated context and cache plaintext DEKs only for a bounded interval.
- **Reason:** Tenant-scoped wrapping permits key rotation and can make encrypted data unreadable after a provider confirms key destruction.
- **Consequences:** Crypto-shredding is not a promise that plaintext, exports, vectors, logs, or historical backups are erased. Production use requires external KMS/BYOK, access controls, recovery tests, and confirmed key-destruction semantics.
- **Evidence:** `engine/security/kms_envelope.py`, tenant-key migration, and crypto-shredding tests.
