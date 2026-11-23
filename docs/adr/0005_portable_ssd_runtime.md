# ADR 0005: Portable host runtime instead of bootable SSD OS

- **Status:** Accepted as the software proof of concept only.
- **Decision:** Run FINESSE and Ollama through an isolated Compose profile with loopback API publishing and persistent application data under mounted portable-runtime directories. Use SQLite WAL and guarded stop/checkpoint scripts.
- **Reason:** The repository can provide a portable application stack without controlling host firmware, drive controller, boot chain, or device unlock hardware.
- **Consequences:** This is not a bootable OS, hardware-encrypted product, host-forensics guarantee, or automatically mounted SSD. Target hardware and host OS validation are required before product claims.
- **Evidence:** `deploy/compose.portable.yaml`, `deploy/PORTABLE_SSD.md`, and portable scripts.
