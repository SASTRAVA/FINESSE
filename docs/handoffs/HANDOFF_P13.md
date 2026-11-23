# P13 handoff: portable SSD server

- Portable Docker Compose uses a loopback-only published API, internal Docker network, persistent drive-mounted app/vault/model directories, SQLite WAL with `synchronous=FULL`, foreign keys, busy timeout, and bounded WAL autocheckpoint.
- Local LLM concurrency defaults to 2; Ollama parallel requests default to 2 and loaded models to 1. Windows start and guarded stop wrappers are provided.
- Ed25519 license/bundle verification is integrated into an opt-in fail-closed portable startup gate; `scripts/verify_portable_bundle.py` verifies signed bundle digests without extracting them. SQLite checkpoint/integrity backup helper and safe-stop's timestamped Qdrant/vault bundle are also available.
- No SSD controller, USB enclosure, firmware, bootable OS, physical unlock, host Docker data/log placement, throughput, GPU, or crash-removal behavior was tested. The profile is a local virtual server using the attached host OS and Docker Engine, not a physical SSD product.
- Signed OCI bundle creation/installation, automatic paired-drive backups, and signed license issuance/key custody remain. Startup enforcement is opt-in until a distribution provides its trusted public key and tenant license.
