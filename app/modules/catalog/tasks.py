"""Catalog background jobs (queue: playlist)."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from celery import shared_task

from app.kernel.container import resolve
from app.kernel.resilience.locks import LockFactory, LockNotAcquiredError
from app.kernel.security.egress import EgressDeniedError, EgressGateway, EgressNetworkError
from app.modules.catalog.fetcher import PlaylistFetchError, fetch_playlist
from app.modules.catalog.parsing import ParsedEntry, parse_text
from app.modules.catalog.probe import ProbeResult, classify_many
from app.modules.catalog.services import CatalogAdminService, PlaylistSyncService

_log = logging.getLogger("catalog.tasks")

PROBE_LIMIT = 300


def _probe_kinds(entries: list[ParsedEntry], *, probe: bool) -> dict[str, str]:
    if not probe:
        return {}
    ambiguous = [e.url for e in entries if e.kind_hint is None][:PROBE_LIMIT]
    results = classify_many(resolve(EgressGateway), ambiguous)
    kinds: dict[str, str] = {}
    for url, result in results.items():
        if result is ProbeResult.DEAD:
            kinds[url] = "dead"
        elif result is ProbeResult.VOD:
            kinds[url] = "vod"
        elif result is ProbeResult.LIVE:
            kinds[url] = "live"
    return kinds


@shared_task(bind=True, name="catalog.sync_playlist")
def sync_playlist(self: Any, playlist_id: int, probe: bool = False) -> dict[str, Any]:
    try:
        with resolve(LockFactory).hold(f"catalog:sync:{playlist_id}", ttl=900):
            self.update_state(state="PROGRESS", meta={"progress": 5, "message": "downloading playlist"})
            source = resolve(CatalogAdminService).playlist_source(playlist_id)
            if not source:
                return {"status": "skipped", "reason": "playlist has no source URL"}
            try:
                entries = fetch_playlist(resolve(EgressGateway), source)
            except (PlaylistFetchError, EgressDeniedError, EgressNetworkError) as exc:
                resolve(PlaylistSyncService).mark_failed(playlist_id, str(exc))
                return {"status": "failed", "error": str(exc)}
            self.update_state(state="PROGRESS", meta={"progress": 40, "message": f"{len(entries)} entries parsed"})
            kinds = _probe_kinds(entries, probe=probe)
            self.update_state(state="PROGRESS", meta={"progress": 75, "message": "writing catalogue"})
            report = resolve(PlaylistSyncService).sync(playlist_id, entries, kinds, replace=True)
            return {"status": "completed", **asdict(report)}
    except LockNotAcquiredError:
        return {"status": "skipped", "reason": "a sync for this playlist is already running"}


@shared_task(bind=True, name="catalog.import_entries")
def import_entries(self: Any, *, text: str | None = None, url: str | None = None, probe: bool = True) -> dict[str, Any]:
    self.update_state(state="PROGRESS", meta={"progress": 5, "message": "reading input"})
    try:
        entries = fetch_playlist(resolve(EgressGateway), url) if url else parse_text(text or "")
    except (PlaylistFetchError, EgressDeniedError, EgressNetworkError) as exc:
        return {"status": "failed", "error": str(exc)}
    if not entries:
        return {"status": "failed", "error": "no playable entries found"}
    self.update_state(state="PROGRESS", meta={"progress": 30, "message": f"probing {len(entries)} streams"})
    kinds = _probe_kinds(entries, probe=probe)
    self.update_state(state="PROGRESS", meta={"progress": 80, "message": "writing catalogue"})
    playlist_id = resolve(CatalogAdminService).manual_playlist_id()
    report = resolve(PlaylistSyncService).sync(playlist_id, entries, kinds, replace=False)
    return {"status": "completed", **asdict(report)}
