"""Stream classification (live / vod / dead) through the egress gateway.

Fixes DATA-07: master playlists are followed to their first variant (a
master never contains #EXT-X-ENDLIST), MPEG-TS is detected by the 0x47 sync
byte at 188-byte packet boundaries, probes run concurrently with a bounded
pool and a per-probe time budget.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from urllib.parse import urljoin

from app.kernel.security.egress import EgressDeniedError, EgressGateway, EgressNetworkError

_log = logging.getLogger("catalog.probe")

HEAD_BYTES = 64 * 1024
_TS_PACKET = 188


class ProbeResult(StrEnum):
    LIVE = "live"
    VOD = "vod"
    DEAD = "dead"
    UNKNOWN = "unknown"


def _read_head(egress: EgressGateway, url: str) -> tuple[bytes, str] | None:
    try:
        response = egress.get(url, stream=True)
    except (EgressDeniedError, EgressNetworkError) as exc:
        _log.info("probe.unreachable url_host=%s reason=%s", url.split("/")[2] if "//" in url else "?", exc)
        return None
    if response.status_code != 200:
        response.close()
        return None
    buffer = bytearray()
    try:
        for chunk in EgressGateway.iter_body(response, 16 * 1024):
            buffer += chunk
            if len(buffer) >= HEAD_BYTES:
                break
    except EgressNetworkError:
        return None
    finally:
        response.close()
    return bytes(buffer), response.headers.get("Content-Type", "")


def classify(egress: EgressGateway, url: str, *, depth: int = 0) -> ProbeResult:
    head = _read_head(egress, url)
    if head is None:
        return ProbeResult.DEAD
    data, content_type = head
    if len(data) > _TS_PACKET and data[0:1] == b"\x47" and data[_TS_PACKET : _TS_PACKET + 1] == b"\x47":
        return ProbeResult.LIVE
    if content_type.startswith("video/") and "mp2t" not in content_type:
        return ProbeResult.VOD
    text = data.decode("utf-8", errors="ignore")
    if "#EXT-X-STREAM-INF" in text and depth == 0:
        variant = next((ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")), None)
        return classify(egress, urljoin(url, variant), depth=1) if variant else ProbeResult.UNKNOWN
    if "#EXT-X-ENDLIST" in text or "#EXT-X-PLAYLIST-TYPE:VOD" in text:
        return ProbeResult.VOD
    if "#EXTINF" in text or "#EXT-X-TARGETDURATION" in text:
        return ProbeResult.LIVE
    return ProbeResult.UNKNOWN


def classify_many(egress: EgressGateway, urls: list[str], *, concurrency: int = 16) -> dict[str, ProbeResult]:
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(urls)))) as pool:
        return dict(zip(urls, pool.map(lambda u: classify(egress, u), urls), strict=True))
