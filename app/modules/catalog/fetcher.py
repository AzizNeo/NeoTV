from __future__ import annotations

from app.kernel.security.egress import EgressGateway
from app.modules.catalog.parsing import ParsedEntry, parse_text

MAX_PLAYLIST_BYTES = 25 * 1024 * 1024


class PlaylistFetchError(Exception):
    pass


def fetch_playlist(egress: EgressGateway, url: str) -> list[ParsedEntry]:
    response = egress.get(url, stream=True)
    if response.status_code != 200:
        response.close()
        raise PlaylistFetchError(f"upstream returned HTTP {response.status_code}")
    if "text/html" in response.headers.get("Content-Type", "").lower():
        response.close()
        raise PlaylistFetchError("URL returned an HTML page, not an M3U playlist")
    body = EgressGateway.read_capped(response, MAX_PLAYLIST_BYTES)
    entries = parse_text(body.decode("utf-8", errors="replace"))
    if not entries:
        raise PlaylistFetchError("no playable entries found")
    return entries
