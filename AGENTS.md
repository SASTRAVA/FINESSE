# FINESSE repository notes

- Keep secrets, tenant data, generated databases, vector indexes, and local model files out of Git.
- Preserve fail-closed tenant checks, sensitivity-aware egress rules, approval gates, and dry-run provider defaults.
- Add every new HTTP route to the generated route-auth inventory and classify intentional public access.
- Run the focused test first, then the project CI checks in `.github/workflows/ci.yml` when dependencies are available.
- Treat `deploy/PORTABLE_SSD.md` as a host-assisted Docker profile; do not describe it as bootable hardware or certification.
- Do not execute security scans or external provider actions against systems without explicit scope and authorization.
