"""End-to-end check of a running Docker demo, through the edge (nginx) like a browser would.

    DEMO_PASSWORD=… python tools/demo_smoke.py [base=http://localhost:8080]

Standard library only, so it runs on CI runners and Windows without the project's venv.
Exit code 0 = the demo is usable: SPA served, API healthy, the generated admin can sign in,
the demo content is there and the TMDB module is mounted.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")
USERNAME = os.environ.get("DEMO_ADMIN_USERNAME", "demo")


def call(path: str, *, body: object = None, token: str | None = None) -> tuple[int, bytes]:
    headers = {"Accept": "application/json", "Origin": BASE}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers)  # noqa: S310 - fixed scheme
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def main() -> int:
    password = os.environ.get("DEMO_PASSWORD")
    if not password:
        raise SystemExit("set DEMO_PASSWORD (docker compose -f compose.demo.yml logs setup shows it)")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: object = "") -> None:
        print(f"{'✔' if ok else '✘'} {name}" + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    status, html = call("/")
    check("SPA served by nginx", status == 200 and b'id="root"' in html, status)
    status, _ = call("/browse")
    check("SPA deep link falls back to index.html", status == 200, status)
    status, _ = call("/demo/sintel-poster.svg")
    check("demo artwork served", status == 200, status)
    status, body = call("/api/v1/health/ready")
    check("API ready (database + redis)", status == 200, body[:200])

    status, body = call("/api/v1/auth/login", body={"username": USERNAME, "password": password})
    check("generated admin signs in", status == 200, body[:200])
    token = json.loads(body).get("access_token") if status == 200 else None
    if token:
        status, body = call("/api/v1/auth/me", token=token)
        role = json.loads(body).get("role") if status == 200 else None
        check("account is an admin", role == "admin", body[:200])
        status, body = call("/api/v1/catalog/admin/channels?per_page=50&include_inactive=true", token=token)
        names = {c["name"] for c in json.loads(body).get("items", [])} if status == 200 else set()
        check("demo content seeded", {"Sintel", "Big Buck Bunny"} <= names, body[:200])
        status, body = call("/api/v1/tmdb/status", token=token)
        check("TMDB module mounted", status == 200 and "configured" in json.loads(body), body[:200])
    status, _ = call("/api/v1/auth/login", body={"username": USERNAME, "password": password + "x"})
    check("wrong password refused", status in (400, 401), status)

    print("demo OK" if not failures else f"demo BROKEN: {', '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
