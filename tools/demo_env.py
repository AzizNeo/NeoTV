"""Secrets of the one-command Docker demo (compose.demo.yml) — generated once, never in git.

    python -m tools.demo_env init            # create the secrets file if missing (idempotent)
    python -m tools.demo_env exec -- CMD …   # run CMD with the secrets in its environment
    python -m tools.demo_env setup           # admin + demo content (+ TMDB if a token is set), then banner
    python -m tools.demo_env banner          # print the demo URL and the admin sign-in

The file lives on the demo's own Docker volume (``DEMO_STATE``), readable only by the
container user: every ``docker compose up`` keeps the same keys (sessions and stored data stay
valid), ``docker compose down -v`` wipes them together with the data. Nothing secret is
written into the repository or the compose file, so a public repo carries no demo password.

Variables already set in the environment win over the file (e.g. a fixed ``SECRET_KEY`` for a
reproducible screenshot run).
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ.get("DEMO_STATE", "/var/lib/neotv/state"))
FILE = STATE / "demo.env"
ADMIN = os.environ.get("DEMO_ADMIN_USERNAME", "demo")
KEYS = ("SECRET_KEY", "NEOTV_ADMIN_PASSWORD")


def _password() -> str:
    # Satisfies the platform's password policy (length, classes, not containing the username).
    return f"Neo-{secrets.token_urlsafe(9)}-{secrets.randbelow(90) + 10}tv!"


def read() -> dict[str, str]:
    if not FILE.exists():
        return {}
    pairs = (line.split("=", 1) for line in FILE.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {k.strip(): v.strip() for k, v in pairs}


def init() -> int:
    current = read()
    missing = [k for k in KEYS if not current.get(k)]
    if not missing:
        print(f"demo secrets: kept ({FILE})")
        return 0
    fresh = {"SECRET_KEY": secrets.token_urlsafe(48), "NEOTV_ADMIN_PASSWORD": _password()}
    current.update({k: fresh[k] for k in missing})
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("".join(f"{k}={v}\n" for k, v in current.items()))
    tmp.replace(FILE)  # atomic: a reader never sees half a file
    print(f"demo secrets: generated {', '.join(missing)} ({FILE})")
    return 0


def exec_(cmd: list[str]) -> int:
    if not cmd:
        raise SystemExit("usage: python -m tools.demo_env exec -- CMD [ARGS…]")
    values = read()
    if not values.get("SECRET_KEY") and not os.environ.get("SECRET_KEY"):
        raise SystemExit(f"{FILE} is missing — the 'secrets' service must run first (python -m tools.demo_env init)")
    for key, value in values.items():
        os.environ.setdefault(key, value)
    # Replaces this process: signals reach CMD directly (tini → CMD). CMD comes from compose.demo.yml.
    os.execvp(cmd[0], cmd)  # noqa: S606
    return 1  # pragma: no cover


def banner() -> int:
    password = os.environ.get("NEOTV_ADMIN_PASSWORD") or read().get("NEOTV_ADMIN_PASSWORD", "?")
    url = os.environ.get("FRONTEND_BASE_URL", "http://localhost:8080")
    rows = [
        "NeoTV demo is ready",
        "",
        f"  Open      {url}",
        f"  Username  {ADMIN}",
        f"  Password  {password}",
        "",
        "Local demo only: test content, fake payments, no e-mails sent.",
    ]
    width = max(map(len, rows)) + 4
    print("╔" + "═" * width + "╗")
    for row in rows:
        print("║  " + row.ljust(width - 2) + "║")
    print("╚" + "═" * width + "╝")
    return 0


def setup() -> int:
    """Idempotent: re-running keeps the admin (never resets a password) and the content."""

    def run(*args: str) -> int:
        return subprocess.run([sys.executable, "-m", *args], check=False).returncode

    if run("flask", "--app", "app.wsgi", "identity", "create-admin", "--username", ADMIN, "--skip-existing"):
        return 1
    if run("tools.seed_demo"):
        return 1
    if os.environ.get("TMDB_READ_TOKEN"):
        # Optional enrichment: TMDB being unreachable must not stop the demo.
        if run("tools.seed_demo", "--tmdb"):
            print("tmdb     ! import incomplete — the demo runs with its own artwork")
    else:
        print("tmdb     - TMDB_READ_TOKEN not set — skipped (optional)")
    return banner()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("init", "exec", "setup", "banner"))
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.action == "init":
        return init()
    if args.action == "banner":
        return banner()
    if args.action == "setup":
        return setup()
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    return exec_(cmd)


if __name__ == "__main__":
    sys.exit(main())
