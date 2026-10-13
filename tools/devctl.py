"""Developer control — one cross-platform entry point for local operations.

    python -m tools.devctl init-env          create/repair .env (generates SECRET_KEY)
    python -m tools.devctl doctor            environment checks (Python, deps, Redis, DB, ffmpeg, Node)
    python -m tools.devctl db-backup         consistent backup of the configured database
    python -m tools.devctl migrate [--to R]  backup, then `flask db upgrade`
    python -m tools.devctl run [--no-frontend] [--no-worker] [--no-beat]
    python -m tools.devctl api | worker | beat
    python -m tools.devctl create-admin --username NAME
    python -m tools.devctl openapi           regenerate openapi/openapi.json
    python -m tools.devctl stream-check [URL ...]  can this server reach its stream sources?

Design rules (RT-08):
* Only processes started *by this tool* are ever signalled — no `taskkill /IM
  python.exe`, no `pkill -f node`.
* Every child runs in its own process group so Ctrl+C / one crashed child shuts
  the whole stack down cleanly on Windows and POSIX.
* Re-executes itself with the project's .venv interpreter when one exists.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WINDOWS = os.name == "nt"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
BACKUP_DIR = ROOT / "instance" / "backups"
QUEUES = "default,outbox,playlist,epg,transcode"


# ── helpers ────────────────────────────────────────────────────────────────


def _child_env() -> dict[str, str]:
    """Child Python processes write UTF-8 regardless of the Windows code page
    (cp1254 etc.): their stdout is a pipe, which otherwise uses the ANSI code
    page and crashes on characters such as '→' or 'ş'."""
    return {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def _venv_python() -> Path | None:
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return None


def _ensure_venv(argv: Sequence[str]) -> int | None:
    """Re-run inside .venv when invoked with another interpreter. Returns the
    child's exit code, or None when already in the right interpreter."""
    venv = _venv_python()
    if venv is None or os.environ.get("NEOTV_DEVCTL_REEXEC") == "1":
        return None
    try:
        same = Path(sys.executable).resolve() == venv.resolve()
    except OSError:
        same = False
    if same:
        return None
    env = {**_child_env(), "NEOTV_DEVCTL_REEXEC": "1"}
    return subprocess.call([str(venv), "-m", "tools.devctl", *argv], cwd=ROOT, env=env)


def _say(msg: str) -> None:
    print(f"devctl │ {msg}", flush=True)


def _flask(*args: str) -> list[str]:
    return [sys.executable, "-m", "flask", "--app", "app.wsgi", *args]


def _settings():  # type: ignore[no-untyped-def]
    sys.path.insert(0, str(ROOT))
    from app.kernel.settings import get_settings

    return get_settings()


# ── init-env ───────────────────────────────────────────────────────────────


def cmd_init_env(args: argparse.Namespace) -> int:
    if not ENV_EXAMPLE.exists():
        _say(".env.example is missing")
        return 2
    if not ENV_FILE.exists() or args.force:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        _say("creating .env from .env.example")
    else:
        text = _sanitize_env(ENV_FILE.read_text(encoding="utf-8-sig", errors="replace"))
    from app.kernel.settings import PLACEHOLDER_SECRETS  # same list the app validates against

    match = re.search(r"^SECRET_KEY=(.*)$", text, flags=re.M)
    current = match.group(1).strip().strip('"').strip("'") if match else ""
    if current.lower() in PLACEHOLDER_SECRETS or len(current) < 32:
        key = secrets.token_urlsafe(48)
        text = (
            re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={key}", text, flags=re.M) if match else f"SECRET_KEY={key}\n{text}"
        )
        _say("generated a new SECRET_KEY (existing sessions/tokens become invalid)")
    else:
        _say("SECRET_KEY already set — kept")
    text = _repair_legacy_env(text)
    if args.local_dev:
        text = _set_env(text, "REDIS_URL", "fakeredis://dev")
        text = _set_env(text, "CELERY_ALWAYS_EAGER", "true")
        text = _set_env(text, "CELERY_BROKER_URL", "memory://")  # eager tasks never touch a broker
        text = _set_env(text, "CELERY_RESULT_BACKEND", "cache+memory://")
        _say("local dev mode: fakeredis + eager Celery (no Redis server needed)")
    ENV_FILE.write_text(text, encoding="utf-8", newline="\n")  # UTF-8 *without* BOM
    _say(f"wrote {ENV_FILE.relative_to(ROOT)}")
    return 0


_ENV_KEY = re.compile(r"^[^A-Za-z_#\n]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _sanitize_env(text: str) -> str:
    """Repair a .env damaged by encoding round-trips (BOM / mojibake before keys)
    and drop duplicate keys. For SECRET_KEY the first non-placeholder value wins;
    for other keys the last assignment wins (dotenv semantics)."""
    from app.kernel.settings import PLACEHOLDER_SECRETS

    lines: list[str] = []
    index: dict[str, int] = {}
    for raw in text.replace("\r\n", "\n").split("\n"):
        match = _ENV_KEY.match(raw)
        if not match:
            stripped = raw.lstrip("\ufeff\ufffd")
            lines.append(stripped if stripped.strip().startswith("#") or not stripped.strip() else raw)
            continue
        key, value = match.groups()
        line = f"{key}={value}"
        if line != raw:
            _say(f"repaired corrupted line for {key}")
        if key in index:
            if key == "SECRET_KEY" and lines[index[key]].split("=", 1)[1].strip().lower() not in PLACEHOLDER_SECRETS:
                continue  # keep the first real secret
            lines[index[key]] = line
            continue
        index[key] = len(lines)
        lines.append(line)
    return "\n".join(lines).rstrip("\n") + "\n"


def _set_env(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{key}=.*$", flags=re.M)
    return pattern.sub(f"{key}={value}", text) if pattern.search(text) else f"{text.rstrip()}\n{key}={value}\n"


def _repair_legacy_env(text: str) -> str:
    """The legacy app ignored DATABASE_URL (it always used instance/database.db)
    while its .env pointed elsewhere. v2 honours DATABASE_URL, so a stale value
    would silently open a *new, empty* database. Repair it explicitly."""
    legacy_db = ROOT / "instance" / "database.db"
    match = re.search(r"^DATABASE_URL=(.*)$", text, flags=re.M)
    if match:
        url = match.group(1).strip().strip('"').strip("'")
        if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
            raw = Path(url[len("sqlite:///") :])
            resolved = raw if raw.is_absolute() else (ROOT / raw).resolve()
            if not resolved.exists() and legacy_db.exists():
                text = text.replace(match.group(0), "DATABASE_URL=sqlite:///instance/database.db")
                _say(f"DATABASE_URL pointed to a missing file ({url}); repointed to the existing instance/database.db")
    for legacy_key, replacement in (("FLASK_APP", "FLASK_APP=app.wsgi"), ("FLASK_ENV", None)):
        pattern = re.compile(rf"^{legacy_key}=.*$\n?", flags=re.M)
        if pattern.search(text):
            text = pattern.sub(f"{replacement}\n" if replacement else "", text)
            _say(f"updated legacy {legacy_key}")
    return text


# ── doctor ─────────────────────────────────────────────────────────────────


def cmd_doctor(_args: argparse.Namespace) -> int:
    problems = 0

    def check(name: str, ok: bool, hint: str = "") -> None:
        nonlocal problems
        print(f"  {'✔' if ok else '✘'} {name}" + ("" if ok or not hint else f"  → {hint}"))
        problems += 0 if ok else 1

    print("NeoTV doctor")
    check(f"Python {sys.version.split()[0]} (>= 3.12)", sys.version_info >= (3, 12), "install Python 3.12+")
    check(".env present", ENV_FILE.exists(), "python -m tools.devctl init-env")
    try:
        settings = _settings()
        check("settings valid", True)
    except Exception as exc:  # pydantic ValidationError and friends
        check("settings valid", False, str(exc).splitlines()[0])
        return 1
    if settings.database_url.startswith("sqlite:///") and settings.database_url != "sqlite:///:memory:":
        db_file = Path(settings.database_url[len("sqlite:///") :])
        check(
            f"SQLite file exists ({db_file})",
            db_file.exists(),
            "wrong DATABASE_URL? run init-env (repairs legacy values) — a new empty DB would be created",
        )
    try:
        from app.kernel.redis import build_redis

        build_redis(settings.redis_url).ping()
        check(f"Redis reachable ({settings.redis_url})", True)
    except Exception as exc:
        check("Redis reachable", False, f"{type(exc).__name__}: start Redis (docker compose up -d redis)")
    try:
        from app.wsgi import app

        with app.app_context():
            from sqlalchemy import text

            from app.kernel.db import db
            from app.kernel.http.health import _migration_head

            current = db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            head = _migration_head()
            check(f"database migrated ({current} / head {head})", current == head, "python -m tools.devctl migrate")
    except Exception as exc:
        check("database reachable / migrated", False, f"{type(exc).__name__}: {exc}"[:160])
    check(
        "ffmpeg on PATH (live transcoding)", shutil.which("ffmpeg") is not None, "optional; needed for ingest channels"
    )
    check("node/npm on PATH (frontend)", shutil.which("npm") is not None, "install Node.js 20+")
    check("frontend dependencies", (ROOT / "frontend" / "node_modules").exists(), "cd frontend && npm ci")
    print("all good" if problems == 0 else f"{problems} problem(s)")
    return 0 if problems == 0 else 1


# ── database ───────────────────────────────────────────────────────────────


def cmd_db_backup(_args: argparse.Namespace) -> int:
    settings = _settings()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    url = settings.database_url
    if url.startswith("sqlite:///"):
        source = Path(url[len("sqlite:///") :])
        if not source.exists():
            _say(f"no SQLite database at {source} — nothing to back up")
            return 0
        target = BACKUP_DIR / f"{source.stem}-{stamp}.db"
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)  # online, consistent copy (WAL-safe)
        _say(f"backup → {target.relative_to(ROOT)}")
        return 0
    if url.startswith("postgresql"):
        pg_dump = shutil.which("pg_dump")
        if pg_dump is None:
            _say("pg_dump not on PATH — take a managed snapshot before migrating")
            return 1
        target = BACKUP_DIR / f"postgres-{stamp}.dump"
        libpq_url = url.replace("postgresql+psycopg://", "postgresql://")
        code = subprocess.call([pg_dump, "--format=custom", f"--file={target}", libpq_url])
        if code == 0:
            _say(f"backup → {target.relative_to(ROOT)}")
        return code
    _say(f"unsupported database URL for backup: {url.split(':', 1)[0]}")
    return 1


def cmd_migrate(args: argparse.Namespace) -> int:
    if not args.skip_backup and cmd_db_backup(args) != 0:
        _say("backup failed — aborting (use --skip-backup to override)")
        return 1
    return subprocess.call(_flask("db", "upgrade", args.to), cwd=ROOT)


# ── processes ──────────────────────────────────────────────────────────────


class Child:
    def __init__(self, name: str, argv: list[str], cwd: Path) -> None:
        self.name = name
        flags: dict[str, object] = {}
        if IS_WINDOWS:
            flags["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            flags["start_new_session"] = True
        self.proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_child_env(),
            **flags,  # type: ignore[arg-type]
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            print(f"[{self.name:<8}] {line.rstrip()}", flush=True)

    def stop(self, timeout: float = 8.0) -> None:
        if self.proc.poll() is not None:
            return
        try:
            if IS_WINDOWS:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
            if IS_WINDOWS:
                subprocess.call(
                    ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )  # only OUR tree (/PID)
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.proc.pid, signal.SIGKILL)


def _worker_argv() -> list[str]:
    # The threads pool works on every OS (prefork does not exist on Windows).
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "app.wsgi:celery",
        "worker",
        "-Q",
        QUEUES,
        "-P",
        "threads",
        "-c",
        "8",
        "--loglevel",
        "INFO",
        "--without-gossip",
        "--without-mingle",
    ]


def _beat_argv() -> list[str]:
    return [sys.executable, "-m", "celery", "-A", "app.wsgi:celery", "beat", "--loglevel", "INFO"]


def _preflight(settings) -> bool:  # type: ignore[no-untyped-def]
    if not settings.celery_always_eager:
        try:
            from app.kernel.redis import build_redis

            build_redis(settings.redis_url).ping()
        except Exception:
            _say(
                f"Redis is not reachable at {settings.redis_url}. Start it (docker compose up -d redis) "
                "or set CELERY_ALWAYS_EAGER=true + REDIS_URL=fakeredis://dev for a Redis-less dev run."
            )
            return False
    return True


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings()
    if not _preflight(settings):
        return 1
    children: list[Child] = [Child("api", [sys.executable, "run.py"], ROOT)]
    if not args.no_worker and not settings.celery_always_eager:
        children.append(Child("worker", _worker_argv(), ROOT))
    if not args.no_beat and not settings.celery_always_eager:
        children.append(Child("beat", _beat_argv(), ROOT))
    frontend = ROOT / "frontend"
    if not args.no_frontend:
        npm = shutil.which("npm.cmd" if IS_WINDOWS else "npm")
        if npm and (frontend / "node_modules").exists():
            children.append(Child("frontend", [npm, "run", "dev"], frontend))
        else:
            _say("frontend skipped (npm missing or `npm ci` not run in frontend/)")
    _say("stack running — Ctrl+C stops everything this tool started")
    exit_code = 0
    try:
        while True:
            for child in children:
                code = child.proc.poll()
                if code is not None:
                    _say(f"'{child.name}' exited with code {code} — stopping the stack")
                    exit_code = code or 1
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            child.stop()
        _say("stopped")
    return exit_code


def cmd_single(argv: list[str]) -> int:
    return subprocess.call(argv, cwd=ROOT, env=_child_env())


# ── CLI ────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devctl", description="NeoTV developer control")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init-env", help="create/repair .env")
    p.add_argument("--force", action="store_true", help="recreate .env from .env.example")
    p.add_argument("--local-dev", action="store_true", help="no Redis needed: fakeredis + eager Celery")
    sub.add_parser("doctor", help="environment checks")
    sub.add_parser("db-backup", help="back up the configured database")
    p = sub.add_parser("migrate", help="backup + flask db upgrade")
    p.add_argument("--to", default="head")
    p.add_argument("--skip-backup", action="store_true")
    p = sub.add_parser("run", help="API + worker + beat + frontend")
    p.add_argument("--no-frontend", action="store_true")
    p.add_argument("--no-worker", action="store_true")
    p.add_argument("--no-beat", action="store_true")
    sub.add_parser("api")
    sub.add_parser("worker")
    sub.add_parser("beat")
    p = sub.add_parser("create-admin")
    p.add_argument("--username", required=True)
    p.add_argument("--email")
    p.add_argument("--skip-existing", action="store_true", help="succeed if the user already exists")
    sub.add_parser("openapi", help="regenerate openapi/openapi.json")
    p = sub.add_parser("stream-check", help="can this server reach its stream sources (and why not)?")
    p.add_argument("urls", nargs="*")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):  # never die printing a child's line on a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    reexec = _ensure_venv(argv)
    if reexec is not None:
        return reexec
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    args = build_parser().parse_args(argv)
    match args.command:
        case "init-env":
            return cmd_init_env(args)
        case "doctor":
            return cmd_doctor(args)
        case "db-backup":
            return cmd_db_backup(args)
        case "migrate":
            return cmd_migrate(args)
        case "run":
            return cmd_run(args)
        case "api":
            return cmd_single([sys.executable, "run.py"])
        case "worker":
            return cmd_single(_worker_argv())
        case "beat":
            return cmd_single(_beat_argv())
        case "create-admin":
            extra = ["--email", args.email] if args.email else []
            extra += ["--skip-existing"] if args.skip_existing else []
            return cmd_single(_flask("identity", "create-admin", "--username", args.username, *extra))
        case "openapi":
            return cmd_single(
                [
                    sys.executable,
                    "-m",
                    "flask",
                    "--app",
                    "tools.openapi_app",
                    "kernel",
                    "openapi",
                    "--out",
                    "openapi/openapi.json",
                ]
            )
        case "stream-check":
            return cmd_single([sys.executable, "-m", "tools.stream_check", *args.urls])
    return 2


if __name__ == "__main__":
    sys.exit(main())
