"""Copy legacy users.json records to PostgreSQL without printing credentials."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_legacy_users() -> list[dict]:
    from engine.config import cfg

    source = cfg.DATA / "users.json"
    if not source.exists():
        return []
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("legacy user file must contain an object keyed by email")
    records = []
    for email, item in payload.items():
        if not isinstance(item, dict) or not re.fullmatch(r"[^@\s]+@[^@\s]+", email):
            raise ValueError("legacy user file contains a malformed identity record")
        user = dict(item)
        user.setdefault("tenant_id", "default")
        if user.get("email", "").lower() != email.lower():
            raise ValueError("legacy user email key does not match its record")
        if not str(user.get("pw_hash", "")).startswith("$2"):
            raise ValueError("legacy user file contains an unsupported password hash")
        tenant_id = str(user["tenant_id"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", tenant_id):
            raise ValueError("legacy user file contains an invalid tenant scope")
        user["email"] = email.lower()
        records.append(user)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write missing records; default is a read-only dry run")
    args = parser.parse_args()
    from engine.config import cfg

    if not cfg.DATABASE_URL.startswith(("postgres://", "postgresql://")):
        raise SystemExit("DATABASE_URL must point to PostgreSQL; no writes were made")
    records = read_legacy_users()
    if not args.apply:
        print(f"dry run: validated {len(records)} legacy user records; no writes made")
        return 0

    from engine.db.storage import storage

    inserted = existing = 0
    for user in records:
        tenant_id = user["tenant_id"]
        email = user["email"].lower()
        if storage.put_if_absent("users", tenant_id, email, user):
            inserted += 1
        else:
            existing += 1
    print(f"migration complete: inserted {inserted}; already present {existing}; source retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
