"""End-to-end *setup* smoke test — the exact path a developer runs on a fresh machine.

    python -m tools.smoke_boot

Runs, in order, against the real tooling (no test fixtures, no mocks):
  1. devctl init-env --local-dev   (.env from .env.example; no Redis needed)
  2. devctl migrate --skip-backup  (empty SQLite → head)
  3. devctl create-admin           (password from NEOTV_ADMIN_PASSWORD)
  4. devctl run --no-frontend      (API through devctl's piped child process)
  5. GET  /api/v1/health/ready     (DB + Redis + migrations all "ok")
  6. POST /api/v1/auth/login       (the admin can actually sign in)
  7. signup → forgot password → read the .eml the console transport wrote →
     reset with the link → sign in with the new password (whole mail pipeline)

Every bug found during the first Windows setup lives on this path (missing
wheels/deps, .env encoding, cp125x console crashes, password prompt), so CI runs
it on Windows + Linux. Exit code 0 = a newcomer's setup works.
"""

from __future__ import annotations

import email.policy
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IS_WINDOWS = os.name == "nt"
PORT = int(os.environ.get("SMOKE_PORT", "5055"))
BASE = f"http://127.0.0.1:{PORT}"
ADMIN_PASSWORD = "Smoke-Test-42!"  # noqa: S105 - throwaway admin of a disposable smoke DB
USER_PASSWORD = "Smoke-User-42!"  # noqa: S105 - throwaway user of a disposable smoke DB
NEW_PASSWORD = "Smoke-Reset-42!"  # noqa: S105
MAIL_DIR = ROOT / "var" / "mail"  # settings.mail_dir default (console transport)
LINK_TOKEN = re.compile(r"#token=([A-Za-z0-9_-]+)")
READY_TIMEOUT_S = 90


def _say(message: str) -> None:
    print(f"smoke │ {message}", flush=True)


def _devctl(*args: str, env: dict[str, str]) -> None:
    _say("devctl " + " ".join(args))
    subprocess.run([sys.executable, "-m", "tools.devctl", *args], cwd=ROOT, env=env, check=True)


def _http(method: str, path: str, body: dict[str, object] | None = None) -> tuple[int, dict[str, object]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)  # noqa: S310 - fixed http://127.0.0.1
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "neotv-smoke/1.0 (CI)")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - fixed http://127.0.0.1
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def _wait_ready(proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    last = "no answer yet"
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"API process exited early with code {proc.returncode}")
        try:
            status, payload = _http("GET", "/api/v1/health/ready")
            if status == 200:
                _say(f"ready: {payload.get('data')}")
                return
            last = f"{status} {payload}"
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last = repr(exc)
        time.sleep(1)
    raise SystemExit(f"API not ready after {READY_TIMEOUT_S}s: {last}")


ERROR_MARKERS = (" ERROR ", "Traceback (most recent call last)", " CRITICAL ")


def _pump(proc: subprocess.Popen[str], errors: list[str]) -> None:
    """Echo the stack's output and remember any error line (a 'working' run must be clean)."""
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip(), flush=True)
        if any(marker in line for marker in ERROR_MARKERS):
            errors.append(line.strip())


def _await_mail(subject_part: str, to: str, since: float, timeout_s: float = 30) -> str:
    """Body of the newest .eml for ``to`` whose subject contains ``subject_part``."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for path in sorted(MAIL_DIR.glob("*.eml"), key=lambda p: p.stat().st_mtime, reverse=True):
            if path.stat().st_mtime < since:
                break
            message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
            if message["To"] == to and subject_part in str(message["Subject"]):
                body = message.get_body(preferencelist=("plain",))
                return body.get_content() if body is not None else ""
        time.sleep(0.5)
    raise SystemExit(f"no '{subject_part}' mail for {to} in {MAIL_DIR} after {timeout_s}s")


def _recovery_flow() -> None:
    started = time.time() - 1
    address = "smoke.user@example.com"
    status, payload = _http(
        "POST", "/api/v1/auth/register", {"username": "smokeuser", "email": address, "password": USER_PASSWORD}
    )
    if status not in (201, 409):
        raise SystemExit(f"signup failed: {status} {payload}")
    if status == 201:
        _await_mail("doğrulayın", address, started)
        _say("verification mail written")
    status, payload = _http("POST", "/api/v1/auth/password/forgot", {"email": address})
    if status != 202:
        raise SystemExit(f"forgot-password failed: {status} {payload}")
    match = LINK_TOKEN.search(_await_mail("sıfırlama", address, started))
    if not match:
        raise SystemExit("reset mail has no #token= link")
    status, payload = _http(
        "POST", "/api/v1/auth/password/reset", {"token": match.group(1), "new_password": NEW_PASSWORD}
    )
    if status != 200:
        raise SystemExit(f"password reset failed: {status} {payload}")
    status, payload = _http("POST", "/api/v1/auth/login", {"username": "smokeuser", "password": NEW_PASSWORD})
    if status != 200:
        raise SystemExit(f"login with the new password failed: {status} {payload}")
    _say("password reset via e-mail link OK")


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGINT)  # type: ignore[attr-defined]
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles/pipes default to cp125x
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "NEOTV_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "PORT": str(PORT),
        "NEOTV_DEVCTL_REEXEC": "1",
    }
    _devctl("init-env", "--local-dev", env=env)
    _devctl("migrate", "--skip-backup", env=env)
    _devctl("create-admin", "--username", "admin", "--skip-existing", env=env)

    flags: dict[str, object] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
        if IS_WINDOWS
        else {"start_new_session": True}
    )
    _say("devctl run --no-frontend")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.devctl", "run", "--no-frontend"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **flags,  # type: ignore[arg-type]
    )
    errors: list[str] = []
    reader = threading.Thread(target=_pump, args=(proc, errors), daemon=True)
    reader.start()
    try:
        _wait_ready(proc)
        status, payload = _http("POST", "/api/v1/auth/login", {"username": "admin", "password": ADMIN_PASSWORD})
        if status != 200 or not (payload.get("data") or {}).get("access_token"):  # type: ignore[union-attr]
            raise SystemExit(f"admin login failed: {status} {payload}")
        _say("admin login OK")
        _recovery_flow()
        time.sleep(2)  # let after-commit work (outbox dispatch) finish and log
    finally:
        _stop(proc)
        reader.join(timeout=5)
    if errors:
        _say(f"FAIL — the stack logged {len(errors)} error line(s):")
        for line in errors[:10]:
            _say(f"  {line}")
        return 1
    _say("PASS — fresh setup works end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
