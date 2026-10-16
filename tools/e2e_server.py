"""Backend for the Playwright suite: a fresh, seeded, throwaway instance on 127.0.0.1:5000.

    python -m tools.e2e_server          # started by frontend/playwright.config.js (webServer)

Every run starts from an empty SQLite file (in-process Redis, eager Celery) so tests never
depend on what a previous run left behind: migrations → test admin → demo content → serve.
The admin's password is a fixed, test-only value (E2E_ADMIN_PASSWORD overrides it); the
instance listens on loopback only and its data is deleted on the next start.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("E2E_STATE", Path(tempfile.gettempdir()) / "neotv-e2e"))
USERNAME = "e2e-admin"
PASSWORD = os.environ.get("E2E_ADMIN_PASSWORD", "Playwright-Only-Secret-2026!")


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "ENV": "test",
            "SECRET_KEY": env.get("SECRET_KEY") or secrets.token_urlsafe(48),
            "DATABASE_URL": f"sqlite:///{(STATE / 'e2e.db').as_posix()}",
            "REDIS_URL": "fakeredis://e2e",
            "CELERY_BROKER_URL": "memory://",
            "CELERY_RESULT_BACKEND": "cache+memory://",
            "CELERY_ALWAYS_EAGER": "true",
            "MAIL_DIR": str(STATE / "mail"),
            "LOG_LEVEL": "WARNING",
            # The browser reaches the API through `vite preview` (same origin), as behind nginx.
            "ALLOWED_ORIGINS": "http://127.0.0.1:4173,http://localhost:4173",
            "FRONTEND_BASE_URL": "http://127.0.0.1:4173",
            # Several tests start playback; a fresh session each time is the realistic path.
            "DEFAULT_MAX_STREAMS": env.get("DEFAULT_MAX_STREAMS", "3"),
            "NEOTV_ADMIN_PASSWORD": PASSWORD,
            "TMDB_READ_TOKEN": "",
            "HOST": "127.0.0.1",
            "PORT": "5000",
        }
    )
    return env


def main() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "e2e.db").unlink(missing_ok=True)
    env = environment()

    def step(*args: str) -> None:
        subprocess.run([sys.executable, "-m", *args], cwd=ROOT, env=env, check=True)

    step("flask", "--app", "app.wsgi", "db", "upgrade")
    step("flask", "--app", "app.wsgi", "identity", "create-admin", "--username", USERNAME)
    step("tools.seed_demo")
    print("e2e backend ready on http://127.0.0.1:5000", flush=True)
    os.chdir(ROOT)
    os.execve(sys.executable, [sys.executable, "run.py"], env)  # noqa: S606 - fixed command
    return 1  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
