"""HLS / progressive proxy for upstream sources (SEC-02).

* Only targets the backend signed during ``open_session`` are fetched.
* Playlists: size-capped, rewritten so every child URI (segments, variants,
  EXT-X-KEY / EXT-X-MAP / EXT-X-MEDIA URIs) is re-signed with the *same*
  grant (same subject + expiry) — the player never sees an upstream URL.
* Segments / progressive media: streamed through in chunks, never buffered
  in memory (PERF-01).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urljoin

from app.kernel.security.egress import EgressGateway
from app.modules.playback.api import INTERNAL_URI_PREFIX, MediaGrant
from app.modules.playback.grants import SignedStreamUrlFactory

M3U8_MIME = "application/vnd.apple.mpegurl"
MAX_PLAYLIST_BYTES = 2 * 1024 * 1024
CHUNK = 64 * 1024
_URI_ATTR = re.compile(r'URI="([^"]+)"')
_PASSTHROUGH_HEADERS = ("Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified", "ETag")


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    status: int
    mimetype: str
    body: bytes | Iterator[bytes]
    headers: dict[str, str]


class UpstreamStatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"upstream HTTP {status}")
        self.status = status


def is_playlist(url: str, content_type: str) -> bool:
    lowered = url.lower().split("?", 1)[0]
    return lowered.endswith((".m3u8", ".m3u")) or "mpegurl" in content_type.lower()


class HlsProxyService:
    def __init__(self, egress: EgressGateway, urls: SignedStreamUrlFactory) -> None:
        self._egress = egress
        self._urls = urls

    def fetch(self, grant: MediaGrant, *, range_header: str | None = None) -> ProxyResponse:
        headers = {"Range": range_header} if range_header else None
        upstream = self._egress.get(grant.target, stream=True, headers=headers)
        if upstream.status_code not in (200, 206):
            upstream.close()
            raise UpstreamStatusError(upstream.status_code)
        content_type = upstream.headers.get("Content-Type", "")
        final_url = upstream.url or grant.target
        if is_playlist(final_url, content_type):
            raw = EgressGateway.read_capped(upstream, MAX_PLAYLIST_BYTES)
            text = raw.decode("utf-8", errors="replace")
            body = self.rewrite(text, base_url=final_url, grant=grant).encode()
            return ProxyResponse(200, M3U8_MIME, body, {"Cache-Control": "no-store"})
        passthrough = {h: upstream.headers[h] for h in _PASSTHROUGH_HEADERS if h in upstream.headers}
        passthrough["Cache-Control"] = "private, max-age=30"
        return ProxyResponse(
            upstream.status_code,
            content_type or "video/mp2t",
            EgressGateway.iter_body(upstream, CHUNK),
            passthrough,
        )

    def rewrite(self, text: str, *, base_url: str, grant: MediaGrant) -> str:
        if not text.lstrip().startswith("#EXTM3U"):
            raise UpstreamStatusError(502)
        out: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if "URI=" in stripped:
                    stripped = _URI_ATTR.sub(
                        lambda m: f'URI="{self._attribute_uri(m.group(1), base_url, grant)}"', stripped
                    )
                out.append(stripped)
            else:
                out.append(self._urls.resign(urljoin(base_url, stripped), grant, proxy=True))
        return "\n".join(out) + "\n"

    def _attribute_uri(self, raw: str, base_url: str, grant: MediaGrant) -> str:
        if raw.startswith(INTERNAL_URI_PREFIX):
            # Our own asset (e.g. DRM key delivery): internal grant, never fetched upstream.
            return self._urls.resign(raw.split("?", 1)[0], grant, proxy=False)
        return self._urls.resign(urljoin(base_url, raw), grant, proxy=True)
