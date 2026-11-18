"""Seed a database: the chart of accounts, role mappings, starter users and mandates.

Idempotent, so it is safe to run on every container start: each loader skips what is
already present. The temporary passwords it prints are the only time they are
visible -- only the hashes are stored -- so they must be changed at first sign-in.

    python -m scripts.seed                       # generate temporary passwords
    python -m scripts.seed --password 'Set-One!'  # one known password, local only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import session_scope
from app.services import seed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--password",
        default=None,
        help="give every seeded user this temporary password (local development only)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.password and settings.env == "production":
        print("refusing to set a shared password in production", file=sys.stderr)
        return 2

    with session_scope() as db:
        passwords = seed.seed_all(db, temporary_password=args.password)

    print(f"seeded {settings.database_url.split('@')[-1]}")
    if passwords:
        print("\ntemporary passwords -- change these at first sign-in:")
        width = max(len(user) for user in passwords)
        for user, password in sorted(passwords.items()):
            print(f"  {user:<{width}}  {password}")
    else:
        print("users already existed; no passwords were reset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
