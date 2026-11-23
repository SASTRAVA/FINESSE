"""Verify a signed FINESSE update bundle without extracting or installing it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    from engine.portable.signatures import SignatureVerificationError, verify_signed_bundle

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("manifest", type=Path,
                        help="Detached signed JSON manifest for the bundle")
    parser.add_argument("--public-key", required=True,
                        help="Trusted Ed25519 public key in PEM or base64 raw form")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        claims = verify_signed_bundle(args.bundle, manifest, args.public_key)
    except (OSError, UnicodeError, json.JSONDecodeError, SignatureVerificationError) as exc:
        parser.error(f"bundle verification failed: {exc}")
    print(json.dumps({"verified": True, "bundle_id": claims["bundle_id"],
                      "sha256": claims["sha256"], "size_bytes": claims["size_bytes"]},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
