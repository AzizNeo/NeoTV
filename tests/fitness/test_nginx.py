"""The edge (deploy/nginx/nginx.conf): protocol routes reach the API, and its log keeps no credentials.

nginx itself is validated in the image build; this pins what a later edit could quietly undo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONF = (ROOT / "deploy/nginx/nginx.conf").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "deploy/nginx/Dockerfile").read_text(encoding="utf-8")


def _locations() -> dict[str, str]:
    return {m[1].strip(): m[2] for m in re.finditer(r"location\s+([^{]+)\{([^{}]*)\}", CONF)}


def test_every_api_location_uses_the_shared_proxy_settings() -> None:
    for spec, body in _locations().items():
        if "proxy_pass http://neotv_api" in body and "kernel/metrics" not in spec:
            assert "include /etc/nginx/snippets/neotv-api-proxy.conf;" in body, spec
    assert "COPY deploy/nginx/api-proxy.conf /etc/nginx/snippets/neotv-api-proxy.conf" in DOCKERFILE


@pytest.mark.parametrize("name", ["player_api.php", "xmltv.php", "get.php", "streaming/timeshift.php"])
def test_the_protocols_root_paths_are_mapped_onto_the_api(name: str) -> None:
    body = _locations()[f"= /{name}"]
    assert f"rewrite ^ /api/v1/xtream/{name} break;" in body


def test_stream_urls_are_mapped_but_the_spas_live_page_is_not() -> None:
    [spec] = [s for s in _locations() if s.startswith("~") and "live|movie|series" in s]
    pattern = re.compile(spec.split(None, 1)[1].strip('"'))
    assert pattern.match("/live/u/p/121.m3u8") and pattern.match("/series/u/p/41.m3u8")
    assert not pattern.match("/live") and not pattern.match("/live/") and not pattern.match("/title/x")


def test_the_access_log_masks_credential_segments_and_drops_queries() -> None:
    assert re.search(r"^\s+access_log /var/log/nginx/access\.log neotv;", CONF, re.M)  # in the server block
    log_format = CONF[CONF.index("log_format neotv") : CONF.index(";", CONF.index("log_format neotv"))]
    assert "$request " not in log_format and "$request_uri" not in log_format and "$args" not in log_format
    assert "$http_referer" not in log_format and "$neotv_log_query" in log_format
    nginx_regex = re.search(r'map \$uri \$neotv_log_path \{\s*"~(.+?)" "(.+?)";', CONF)
    assert nginx_regex
    regex = re.compile(nginx_regex[1].replace("(?<", "(?P<"))
    replacement = nginx_regex[2].replace("$head", r"\g<head>").replace("$tail", r"\g<tail>")
    assert regex.sub(replacement, "/api/v1/xtream/live/user1/pass1/121.m3u8") == "/api/v1/xtream/live/***/***/121.m3u8"
    assert regex.sub(replacement, "/live") == "/live"


def test_archive_files_are_only_served_after_the_api_checked_the_grant() -> None:
    start = CONF.index("location /_protected_archive/ {")
    body = CONF[start : CONF.index("\n    }", start)]  # has a nested types {} block
    assert "internal;" in body and "alias /var/lib/neotv/archive/;" in body


def test_catch_up_urls_are_mapped_and_their_credentials_masked_in_the_log() -> None:
    [spec] = [s for s in _locations() if s.startswith("~") and "timeshift" in s]
    pattern = re.compile(spec.split(None, 1)[1].strip('"'))
    assert pattern.match("/timeshift/u/p/45/2026-10-20:18-00/32.m3u8")
    assert not pattern.match("/timeshift/u/p/32.m3u8")
    nginx_regex = re.search(r'map \$uri \$neotv_log_path \{\s*"~(.+?)" "(.+?)";', CONF)
    assert nginx_regex
    regex = re.compile(nginx_regex[1].replace("(?<", "(?P<"))
    replacement = nginx_regex[2].replace("$head", r"\g<head>").replace("$tail", r"\g<tail>")
    masked = regex.sub(replacement, "/api/v1/xtream/timeshift/user1/pass1/45/2026-10-20:18-00/32.m3u8")
    assert masked == "/api/v1/xtream/timeshift/***/***/45/2026-10-20:18-00/32.m3u8"
