"""Per-request plumbing: proxy headers, request id, security headers, CORS."""

from __future__ import annotations

import re
import time
import uuid

from flask import Flask, Response, g, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
#: The API returns data (JSON, playlists, segments), never documents: nothing in a response may
#: execute, load anything or be framed. The SPA's own policy lives in deploy/nginx/security-headers.conf.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def install(app: Flask, *, allowed_origins: list[str], trusted_proxy_count: int, hsts_max_age_s: int = 0) -> None:
    """``hsts_max_age_s`` > 0 sends Strict-Transport-Security on HTTPS requests only (as seen
    through the trusted proxy): browsers ignore it over plain HTTP, and sending it there would
    only confuse a reader of the headers."""
    if trusted_proxy_count:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=trusted_proxy_count, x_proto=trusted_proxy_count, x_host=trusted_proxy_count
        )

    CORS(
        app,
        resources={r"/api/*": {"origins": allowed_origins}},
        supports_credentials=True,
        expose_headers=["X-Request-ID", "Retry-After", "Idempotent-Replayed", "Location"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Device-ID",
            "X-Profile-Token",
            "X-Request-ID",
            "X-Requested-With",
        ],
    )

    @app.before_request
    def _request_id() -> None:
        inbound = request.headers.get("X-Request-ID", "")
        g.request_id = inbound if _REQUEST_ID.fullmatch(inbound) else uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def _headers(response: Response) -> Response:
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.path.startswith("/api/"):
            response.headers.setdefault("Content-Security-Policy", API_CSP)
        if hsts_max_age_s and request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", f"max-age={hsts_max_age_s}; includeSubDomains")
        if request.path.startswith("/api/") and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response
