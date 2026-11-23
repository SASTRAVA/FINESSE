# Production gate evidence format

`python scripts/verify_production_gates.py --strict` checks evidence entries for
G1-G12 and U1-U8. The default manifest path is
`docs/readiness/production_evidence.json`; it is intentionally absent until
owners review and submit evidence. Each entry must have `status: PASS` and at
least one repository-contained evidence file. The verifier hashes every file
into its output and fails when a gate or pillar is missing, evidence is absent,
or the report cannot be signed.

Use an evidence manifest with this structure after reviewers have approved the
underlying run/test records:

```json
{
  "evidence": {
    "G3": {
      "status": "PASS",
      "evidence": ["docs/security/route_auth_inventory.json"]
    }
  }
}
```

The example is deliberately incomplete and will fail strict verification.
Populate every gate and pillar only with current, reviewed evidence. U2 and U7
require product owners to provide the missing source mapping. Set
`FINESSE_SIGNOFF_PRIVATE_KEY` to an externally managed Ed25519 PEM private key
only in a protected signing environment. Never add that private key or a
customer evidence bundle to the repository. Outputs may be written using
`--json-out` and `--markdown-out`; generated outputs are not attestation or
compliance certification by themselves.
