# Portable FINESSE licensing and update verification

The portable runtime supports signed offline licenses. Licensing is opt-in in
the repository's example profile because this source tree does not own a signing
authority or customer license. A distribution enables it with
`PORTABLE_LICENSE_REQUIRED=true`, supplies the trusted Ed25519 public key in
`PORTABLE_LICENSE_PUBLIC_KEY`, sets `PORTABLE_TENANT_ID`, and places the signed
document at `portable-runtime/data/license.json` (mounted as
`/app/data/license.json`). Startup fails closed if the document, signature,
validity interval, trusted key, or tenant binding is invalid.

The license document contains `claims` and a base64 Ed25519 `signature`. Claims
must include `product: FINESSE`, a nonempty `license_id` and `tenant_id`, a list
of `features`, and integer `issued_at`, `not_before`, and `expires_at` Unix
timestamps. The signature covers canonical JSON for the claims. The matching
private signing key must stay in the distributor's key-management system and
must never be placed in this repository or the portable device.

Signed update bundles can be checked before installation without extraction:

```powershell
python scripts/verify_portable_bundle.py update.tar manifest.json --public-key $env:PORTABLE_LICENSE_PUBLIC_KEY
```

The command verifies signature, content SHA-256, and byte length. It does not
install or roll back updates. The repository still needs a signed OCI bundle
builder/installer, rollback transaction, license issuance service, and key
custody procedures before it can claim a production portable distribution.
