"""Catch-up archive storage (ADR-0012): a port, a local-directory adapter, and the disk guard.

Layout — one file per segment, named by its UTC start, grouped by hour::

    <ARCHIVE_ROOT>/<channel id>/<YYYYMMDD>/<HH>/<YYYYMMDDTHHMMSSZ>.ts

Any time window is listed from names alone (no database row per segment). A segment's duration
is the gap to the next one; a gap well above the nominal length is a hole in the recording (the
source was down) and is marked as a discontinuity — nothing is invented to fill it.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

#: Nominal segment length the recorder cuts at (at the next key frame).
SEGMENT_SECONDS = 6
#: A gap above this between two segment starts is a hole, not a long segment.
_MAX_GAP_S = SEGMENT_SECONDS * 2
_NAME = re.compile(r"^(\d{8}T\d{6}Z)\.ts$")
_STAMP = "%Y%m%dT%H%M%SZ"


@dataclass(frozen=True, slots=True)
class Segment:
    start: datetime
    duration_s: float
    key: str  # path relative to the archive root, "/" separated
    discontinuity: bool = False  # a hole in the recording precedes this segment


@dataclass(frozen=True, slots=True)
class DiskUsage:
    used: int
    total: int

    @property
    def ratio(self) -> float:
        return self.used / self.total if self.total else 1.0


class ArchiveStorage(Protocol):
    """Port: where recordings live. The first adapter is a local directory; an object store can
    replace it without changing the recorder's callers or playback."""

    def channel_dir(self, channel_id: int) -> Path: ...
    def segment_name(self, start: datetime) -> str: ...
    def segments(self, channel_id: int, start: datetime, end: datetime, *, now: datetime) -> list[Segment]: ...
    def newest(self, channel_id: int) -> datetime | None: ...
    def channels(self) -> list[int]: ...
    def delete_before(self, channel_id: int, cutoff: datetime) -> int: ...
    def delete_channel(self, channel_id: int) -> int: ...
    def usage(self) -> DiskUsage: ...


def parse_start(name: str) -> datetime | None:
    match = _NAME.match(name)
    return datetime.strptime(match[1], _STAMP).replace(tzinfo=UTC) if match else None


class LocalArchiveStorage:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def channel_dir(self, channel_id: int) -> Path:
        if not isinstance(channel_id, int) or isinstance(channel_id, bool) or channel_id <= 0:
            raise ValueError("channel id must be a positive integer")
        return self._root / str(channel_id)

    def segment_name(self, start: datetime) -> str:
        start = start.astimezone(UTC)
        return f"{start:%Y%m%d}/{start:%H}/{start.strftime(_STAMP)}.ts"

    def segments(self, channel_id: int, start: datetime, end: datetime, *, now: datetime) -> list[Segment]:
        """Complete segments overlapping [start, end). One still being written is left out."""
        lookback = start - timedelta(seconds=_MAX_GAP_S)  # the segment that covers `start` began earlier
        starts = [s for s in self._starts(channel_id, lookback, end) if s < end]
        out: list[Segment] = []
        for index, begin in enumerate(starts):
            following = starts[index + 1] if index + 1 < len(starts) else None
            gap = (following - begin).total_seconds() if following else None
            duration = gap if gap is not None and 0 < gap <= _MAX_GAP_S else float(SEGMENT_SECONDS)
            if following is None and begin + timedelta(seconds=SEGMENT_SECONDS) > now:
                break  # the recorder is still writing it
            if begin + timedelta(seconds=duration) <= start:
                continue
            previous = starts[index - 1] if index else None
            hole = previous is not None and (begin - previous).total_seconds() > _MAX_GAP_S
            key = f"{channel_id}/{self.segment_name(begin)}"
            out.append(Segment(start=begin, duration_s=duration, key=key, discontinuity=bool(out) and hole))
        return out

    def newest(self, channel_id: int) -> datetime | None:
        base = self.channel_dir(channel_id)
        for day in sorted(_dirs(base), reverse=True):
            for hour in sorted(_dirs(base / day), reverse=True):
                stamps = [s for s in (parse_start(f.name) for f in (base / day / hour).iterdir()) if s]
                if stamps:
                    return max(stamps)
        return None

    def channels(self) -> list[int]:
        return sorted(int(d) for d in _dirs(self._root) if d.isdigit())

    def delete_before(self, channel_id: int, cutoff: datetime) -> int:
        """Removes every segment that starts before ``cutoff``; returns how many files went."""
        base = self.channel_dir(channel_id)
        cutoff = cutoff.astimezone(UTC)
        removed = 0
        for day in _dirs(base):
            for hour in _dirs(base / day):
                folder = base / day / hour
                hour_start = _hour_start(day, hour)
                if hour_start is None:
                    continue
                if hour_start + timedelta(hours=1) <= cutoff:  # the whole hour is out of the window
                    removed += sum(1 for f in folder.iterdir() if f.is_file())
                    shutil.rmtree(folder, ignore_errors=True)
                    continue
                if hour_start < cutoff:
                    for file in folder.iterdir():
                        stamp = parse_start(file.name)
                        if stamp is not None and stamp < cutoff:
                            file.unlink(missing_ok=True)
                            removed += 1
            _remove_if_empty(base / day)
        return removed

    def delete_channel(self, channel_id: int) -> int:
        base = self.channel_dir(channel_id)
        if not base.exists():
            return 0
        removed = sum(1 for f in base.rglob("*.ts"))
        shutil.rmtree(base, ignore_errors=True)
        return removed

    def usage(self) -> DiskUsage:
        self._root.mkdir(parents=True, exist_ok=True)
        disk = shutil.disk_usage(self._root)
        return DiskUsage(used=disk.used, total=disk.total)

    def _starts(self, channel_id: int, start: datetime, end: datetime) -> Iterator[datetime]:
        base = self.channel_dir(channel_id)
        hour = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        while hour < end:
            folder = base / f"{hour:%Y%m%d}" / f"{hour:%H}"
            if folder.is_dir():
                stamps = sorted(s for s in (parse_start(f.name) for f in folder.iterdir()) if s)
                yield from (s for s in stamps if s >= start)
            hour += timedelta(hours=1)


#: A recorded segment's key inside one channel: YYYYMMDD/HH/YYYYMMDDTHHMMSSZ.ts
SEGMENT_KEY = re.compile(r"^(\d{8})/(\d{2})/(\d{8}T\d{6}Z)\.ts$")


def render_playlist(segments: list[Segment], *, complete: bool, query: str) -> str:
    """An HLS media playlist for a window. ``complete``: the window has ended (VOD, ENDLIST);
    otherwise it is still on air (EVENT, no ENDLIST — players poll it, start over works).
    Segment URIs are relative to the window's directory and carry the window's grant."""
    target = max([SEGMENT_SECONDS, *(int(-(-s.duration_s // 1)) for s in segments)])
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        f"#EXT-X-PLAYLIST-TYPE:{'VOD' if complete else 'EVENT'}",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    for index, segment in enumerate(segments):
        if segment.discontinuity:
            lines.append("#EXT-X-DISCONTINUITY")
        if index == 0 or segment.discontinuity:  # wall-clock anchors: the guide and the player agree
            lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{segment.start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}")
        lines.append(f"#EXTINF:{segment.duration_s:.3f},")
        key = segment.key.split("/", 1)[1]  # drop the channel id: URIs are relative to the window
        lines.append(f"{key}?{query}" if query else key)
    if complete:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


class ArchiveDiskGuard:
    """Whether recording may run, with hysteresis so it does not flap around one threshold.

    At ``stop_ratio`` disk use nothing is recorded (existing archives stay and keep playing);
    recording resumes once use falls below ``resume_ratio`` (retention or an operator freed space).
    """

    def __init__(self, storage: ArchiveStorage, *, stop_ratio: float, resume_ratio: float) -> None:
        if not 0 < resume_ratio < stop_ratio <= 1:
            raise ValueError("ARCHIVE_RESUME_RATIO must be below ARCHIVE_STOP_RATIO")
        self._storage = storage
        self._stop = stop_ratio
        self._resume = resume_ratio
        self._allowed = True

    def may_record(self) -> bool:
        ratio = self._storage.usage().ratio
        if ratio >= self._stop:
            self._allowed = False
        elif ratio < self._resume:
            self._allowed = True
        return self._allowed


def _dirs(path: Path) -> list[str]:
    return [p.name for p in path.iterdir() if p.is_dir()] if path.is_dir() else []


def _hour_start(day: str, hour: str) -> datetime | None:
    try:
        return datetime.strptime(f"{day}{hour}", "%Y%m%d%H").replace(tzinfo=UTC)
    except ValueError:
        return None


def _remove_if_empty(path: Path) -> None:
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
