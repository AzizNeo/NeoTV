"""Prepare the viewer accounts a load test signs in with (k6: deploy/load/neotv.js).

    LOAD_PASSWORD=… python -m tools.load_seed [--count 50]

Accounts are created through the identity service, not the public API: registration is rate
limited per IP (as it must be), and a load test that registers its own users would only measure
that limit. Rate limits stay on during the test — the scenarios are paced to stay under them.

Idempotent (existing accounts are kept), named ``load-0001`` … so they are easy to find and
remove, and refused in production: accounts with a shared, known password do not belong there.
"""

from __future__ import annotations

import argparse
import os
import sys

PREFIX = "load-"


def username(index: int) -> str:
    return f"{PREFIX}{index:04d}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=50, help="number of viewer accounts (default 50)")
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 5000:
        parser.error("--count must be between 1 and 5000")
    password = os.environ.get("LOAD_PASSWORD")
    if not password:
        raise SystemExit("set LOAD_PASSWORD (the k6 script signs in with the same value)")

    # Checked before the settings are loaded too: a production .env that fails validation here
    # must still be refused, not merely crash.
    if os.environ.get("ENV", "").lower() == "prod":
        raise SystemExit("refused: load-test accounts are never created in production (ENV=prod)")

    from app.kernel.container import resolve
    from app.kernel.settings import get_settings

    if get_settings().env == "prod":
        raise SystemExit("refused: load-test accounts are never created in production (ENV=prod)")

    from app.wsgi import app

    with app.app_context():
        from app.modules.identity.domain import UsernameTakenError
        from app.modules.identity.services import AuthService

        auth = resolve(AuthService)
        created = 0
        for index in range(1, args.count + 1):
            try:
                auth.register(username=username(index), email=None, password=password)
                created += 1
            except UsernameTakenError:
                pass
    print(f"load accounts: {args.count} ready ({created} created, {args.count - created} existed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
