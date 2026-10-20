"""Catch-up archive storage: layout, windows from names alone, holes, retention, the disk guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.modules.live.archive import (
    SEGMENT_SECONDS,
    ArchiveDiskGuard,
    DiskUsage,
    LocalArchiveStorage,
    parse_start,
)

T0 = datetime(2026, 10, 20, 11, 59, 48, tzinfo=UTC)


def _record(storage: LocalArchiveStorage, channel: int, starts: list[datetime]) -> None:
    for start in starts:
        path = storage.channel_dir(channel) / storage.segment_name(start)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ts")


def _every(start: datetime, count: int, step: int = SEGMENT_SECONDS) -> list[datetime]:
    return [start + timedelta(seconds=step * n) for n in range(count)]


@pytest.fixture
def storage(tmp_path: Path) -> LocalArchiveStorage:
    return LocalArchiveStorage(tmp_path)


def test_layout_is_by_channel_day_and_hour_in_utc(storage: LocalArchiveStorage) -> None:
    local = datetime(2026, 10, 20, 2, 30, 6, tzinfo=UTC).astimezone()  # any zone in, UTC on disk
    assert storage.segment_name(local) == "20261020/02/20261020T023006Z.ts"
    assert parse_start("20261020T023006Z.ts") == datetime(2026, 10, 20, 2, 30, 6, tzinfo=UTC)
    assert parse_start("notes.txt") is None and parse_start("20261020T023006Z.ts.tmp") is None
    for bad in (0, -1, True):
        with pytest.raises(ValueError):
            storage.channel_dir(bad)  # type: ignore[arg-type]


def test_a_window_across_hours_lists_complete_segments_with_their_durations(storage: LocalArchiveStorage) -> None:
    _record(storage, 3, _every(T0, 10))  # 11:59:48 … 12:00:42, across the hour
    now = T0 + timedelta(minutes=10)
    segments = storage.segments(3, T0 + timedelta(seconds=7), T0 + timedelta(seconds=30), now=now)
    assert [s.start for s in segments] == _every(T0 + timedelta(seconds=6), 4)  # the one covering 7 s is in
    assert {s.duration_s for s in segments} == {float(SEGMENT_SECONDS)}
    assert segments[0].key == "3/20261020/11/20261020T115954Z.ts"
    assert segments[2].key.startswith("3/20261020/12/")


def test_a_hole_is_marked_and_never_filled(storage: LocalArchiveStorage) -> None:
    _record(storage, 3, [*_every(T0, 3), *_every(T0 + timedelta(minutes=5), 3)])
    segments = storage.segments(3, T0, T0 + timedelta(minutes=6), now=T0 + timedelta(hours=1))
    assert len(segments) == 6
    assert [s.discontinuity for s in segments] == [False, False, False, True, False, False]
    assert segments[2].duration_s == SEGMENT_SECONDS  # the last one before the hole keeps its nominal length


def test_the_segment_being_written_is_left_out(storage: LocalArchiveStorage) -> None:
    _record(storage, 3, _every(T0, 3))
    writing = T0 + timedelta(seconds=12 + 2)  # the third segment began 2 s ago
    assert [s.start for s in storage.segments(3, T0, writing, now=writing)] == _every(T0, 2)
    assert storage.newest(3) == T0 + timedelta(seconds=12)
    assert storage.newest(4) is None


def test_retention_removes_what_is_older_than_the_cutoff(storage: LocalArchiveStorage) -> None:
    _record(storage, 3, _every(T0 - timedelta(hours=2), 3) + _every(T0, 10))
    _record(storage, 9, _every(T0, 2))
    assert storage.channels() == [3, 9]
    cutoff = T0 + timedelta(seconds=30)
    assert storage.delete_before(3, cutoff) == 3 + 5  # two hours back (whole dir) + five before the cutoff
    remaining = storage.segments(3, T0 - timedelta(hours=3), T0 + timedelta(hours=1), now=T0 + timedelta(hours=2))
    assert remaining[0].start == cutoff
    assert not (storage.channel_dir(3) / "20261020" / "09").exists()
    assert storage.delete_channel(9) == 2 and storage.channels() == [3]
    assert storage.delete_channel(42) == 0


class _Disk:
    def __init__(self) -> None:
        self.ratio = 0.5

    def usage(self) -> DiskUsage:
        return DiskUsage(used=int(self.ratio * 1000), total=1000)


def test_the_disk_guard_stops_at_90_and_resumes_below_85() -> None:
    disk = _Disk()
    guard = ArchiveDiskGuard(disk, stop_ratio=0.9, resume_ratio=0.85)  # type: ignore[arg-type]
    seen = []
    for ratio in (0.5, 0.89, 0.9, 0.88, 0.86, 0.84, 0.95):
        disk.ratio = ratio
        seen.append(guard.may_record())
    assert seen == [True, True, False, False, False, True, False]  # no flapping between 85 and 90
    with pytest.raises(ValueError, match="RESUME"):
        ArchiveDiskGuard(disk, stop_ratio=0.8, resume_ratio=0.85)  # type: ignore[arg-type]
    assert DiskUsage(used=1, total=0).ratio == 1.0  # an unreadable volume counts as full


def test_the_playlist_marks_holes_and_ends_only_when_the_window_has() -> None:
    from app.modules.live.archive import Segment, render_playlist

    segments = [
        Segment(T0, 6.0, "3/20261020/11/20261020T115948Z.ts"),
        Segment(T0 + timedelta(seconds=6), 6.4, "3/20261020/11/20261020T115954Z.ts"),
        Segment(T0 + timedelta(minutes=5), 6.0, "3/20261020/12/20261020T120448Z.ts", discontinuity=True),
    ]
    vod = render_playlist(segments, complete=True, query="sig=x").splitlines()
    assert vod[:6] == [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:7",  # rounded up from 6.4
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    assert vod[6] == "#EXT-X-PROGRAM-DATE-TIME:2026-10-20T11:59:48.000Z"
    assert "20261020/11/20261020T115948Z.ts?sig=x" in vod  # relative to the window, channel id dropped
    hole = vod.index("#EXT-X-DISCONTINUITY")
    assert vod[hole + 1] == "#EXT-X-PROGRAM-DATE-TIME:2026-10-20T12:04:48.000Z" and vod[-1] == "#EXT-X-ENDLIST"
    live = render_playlist(segments, complete=False, query="").splitlines()
    assert "#EXT-X-PLAYLIST-TYPE:EVENT" in live and "#EXT-X-ENDLIST" not in live
    assert render_playlist([], complete=False, query="").count("#EXTINF") == 0


def test_a_six_hour_window_is_listed_and_rendered_quickly(storage: LocalArchiveStorage) -> None:
    """The playlist is built from directory listings on every request: 3 600 segments (6 h, the
    longest window) must stay well under a second, or catch-up does not scale (ADR-0012)."""
    import time

    from app.modules.live.archive import render_playlist

    start = T0 - timedelta(hours=6)
    _record(storage, 3, _every(start, 6 * 3600 // SEGMENT_SECONDS))
    began = time.perf_counter()
    segments = storage.segments(3, start, T0, now=T0 + timedelta(minutes=1))
    text = render_playlist(segments, complete=True, query="u=x&s=1.t&exp=1&sig=y")
    elapsed = time.perf_counter() - began
    assert len(segments) == 3600 and text.count("#EXTINF") == 3600
    assert elapsed < 1.0, f"{elapsed:.3f}s for a 6-hour window"
