"""URL redaction (shared_kernel.redaction) and the gunicorn access log that uses it."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.kernel.observability.access_log import RedactingLogger
from app.shared_kernel.redaction import redact_path, redact_query, redact_target


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/live/user1/pass1/121.m3u8", "/live/***/***/121.m3u8"),
        ("/api/v1/xtream/movie/u/p/11.m3u8", "/api/v1/xtream/movie/***/***/11.m3u8"),
        ("/series/u/p/41.m3u8?x=1", "/series/***/***/41.m3u8?x=1"),
        ("/timeshift/u/p/60/2026-10-18:12-00/32.ts", "/timeshift/***/***/60/2026-10-18:12-00/32.ts"),
        ("/player_api.php?username=u&password=p&action=a", "/player_api.php?username=***&password=***&action=a"),
        ("/api/v1/playback/proxy?u=abc&s=1.tok&exp=9&sig=SECRET", "/api/v1/playback/proxy?u=abc&s=1.tok&exp=9&sig=***"),
        (
            "https://tv.example.com/live/u/p/1.m3u8?Password=x",
            "https://tv.example.com/live/***/***/1.m3u8?Password=***",
        ),
        ("http://provider:8080/live/acc/pw/77.ts", "http://provider:8080/live/***/***/77.ts"),
        # Untouched: the SPA's own pages and ordinary queries keep their exact encoding.
        ("/live", "/live"),
        ("/live/abc", "/live/abc"),
        ("/api/v1/titles?search=a%20b&page=2", "/api/v1/titles?search=a%20b&page=2"),
        ("https://tv.example.com", "https://tv.example.com"),
        ("", ""),
    ],
)
def test_redact_target(target: str, expected: str) -> None:
    assert redact_target(target) == expected


def test_parts_alone() -> None:
    assert redact_path("/movie/u/p/1.m3u8") == "/movie/***/***/1.m3u8"
    assert redact_query("token=abc&keep=1") == "token=***&keep=1"
    assert redact_query("") == ""


def test_gunicorn_access_log_atoms_are_redacted() -> None:
    from gunicorn.config import Config

    logger = RedactingLogger(Config())
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": "/live/user1/pass1/121.m3u8?password=pass1",
        "PATH_INFO": "/live/user1/pass1/121.m3u8",
        "QUERY_STRING": "password=pass1",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "10.0.0.1",
        "HTTP_REFERER": "https://tv.example.com/get.php?username=user1&password=pass1",
    }
    resp = SimpleNamespace(status="200 OK", sent=10, headers=[])
    atoms = logger.atoms(resp, SimpleNamespace(headers=[]), environ, timedelta(milliseconds=5))
    line = repr(atoms)
    assert "pass1" not in line and "user1" not in line
    assert atoms["r"] == "GET /live/***/***/121.m3u8?password=*** HTTP/1.1"
    assert atoms["U"] == "/live/***/***/121.m3u8" and atoms["q"] == "password=***"
