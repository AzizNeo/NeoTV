"""Security headers: the API's own (Flask) and the SPA's (deploy/nginx/security-headers.conf).

The SPA policy is exercised in a real browser by the Playwright suite; here we pin its *shape*
(what must never be loosened) and the nginx wiring, which has a classic trap: a location that
declares any add_header silently drops every inherited one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.kernel.http.request_context import API_CSP
from tests.support.factory import make_app

ROOT = Path(__file__).resolve().parents[2]
SNIPPET = ROOT / "deploy/nginx/security-headers.conf"
NGINX = ROOT / "deploy/nginx/nginx.conf"
_LINE = re.compile(r'^\s*add_header\s+([A-Za-z-]+)\s+(?:"([^"]*)"|(\$\w+))\s+always;\s*$')


def _snippet() -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in SNIPPET.read_text(encoding="utf-8").splitlines():
        if raw.strip() and not raw.strip().startswith("#"):
            match = _LINE.match(raw)
            assert match, f"unexpected line in {SNIPPET.name}: {raw!r}"
            headers[match[1]] = match[2] if match[2] is not None else match[3]
    return headers


def _csp(value: str) -> dict[str, list[str]]:
    return {d.split()[0]: d.split()[1:] for d in (part.strip() for part in value.split(";")) if d}


# ── API (Flask) ─────────────────────────────────────────────────────────────
def test_api_responses_forbid_everything_a_document_could_do(api):
    response = api.client.get("/api/v1/health/live")
    assert response.headers["Content-Security-Policy"] == API_CSP
    assert _csp(API_CSP)["default-src"] == ["'none'"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" not in response.headers  # plain HTTP: never


@pytest.mark.parametrize(("proto", "expected"), [("https", True), ("http", False)])
def test_hsts_only_over_https_as_reported_by_the_trusted_proxy(proto, expected):
    client = make_app(trusted_proxy_count=1, hsts_max_age_s=31_536_000).test_client()
    response = client.get("/api/v1/health/live", headers={"X-Forwarded-Proto": proto})
    if expected:
        assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    else:
        assert "Strict-Transport-Security" not in response.headers


def test_hsts_can_be_switched_off():
    client = make_app(trusted_proxy_count=1, hsts_max_age_s=0).test_client()
    response = client.get("/api/v1/health/live", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" not in response.headers


def test_an_untrusted_client_cannot_claim_https():
    # Without a trusted proxy, X-Forwarded-Proto from the client is ignored.
    client = make_app(trusted_proxy_count=0, hsts_max_age_s=31_536_000).test_client()
    response = client.get("/api/v1/health/live", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" not in response.headers


# ── SPA (nginx snippet) ─────────────────────────────────────────────────────
def test_spa_policy_never_allows_script_injection():
    csp = _csp(_snippet()["Content-Security-Policy"])
    assert csp["script-src"] == ["'self'"], "no inline, eval, CDN or wildcard for scripts"
    for directive, sources in csp.items():
        assert not {"'unsafe-inline'", "'unsafe-eval'", "*"} & set(sources), f"{directive} was loosened"
    assert csp["object-src"] == ["'none'"]
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["base-uri"] == ["'self'"]
    assert csp["style-src"] == ["'self'"]


def test_spa_headers_complete():
    headers = _snippet()
    assert headers["Strict-Transport-Security"] == "$neotv_hsts"  # set only for HTTPS (map in nginx.conf)
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "camera=()" in headers["Permissions-Policy"]
    assert "fullscreen" not in headers["Permissions-Policy"]  # the player needs it (and picture-in-picture)
    assert "$neotv_hsts" in NGINX.read_text(encoding="utf-8")


def test_every_nginx_location_that_sets_headers_includes_the_shared_set():
    """nginx: one add_header in a location drops all inherited ones."""
    text = NGINX.read_text(encoding="utf-8")
    for match in re.finditer(r"location\s+([^{]+)\{(.*?)\n    \}", text, flags=re.S):
        path, body = match[1].strip(), match[2]
        serves_app = "try_files" in body
        if serves_app:
            assert "include /etc/nginx/snippets/neotv-security-headers.conf;" in body, f"location {path}"
