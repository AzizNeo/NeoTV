"""The catch-up recorder (ADR-0012): one long-running process that keeps every archived channel
recorded, whether or not anyone watches.

* **One recorder per channel, cluster-wide.** A Redis lease per channel (owner id, 30 s, renewed
  every tick): several recorder replicas share the channels, and a replica that dies hands its
  channels over within the lease time.
* **No transcoding.** ``-c copy`` into ~6 s MPEG-TS segments (cut at key frames) named by their UTC
  start (``-strftime`` with ``TZ=UTC``): the cost of recording is disk, not CPU.
* **External sources are checked first** with the egress policy (no private addresses, allowed
  ports), as every other outbound request is — ffmpeg itself would follow anything.
* **Failures back off** exponentially (5 s … 5 min) per channel and reset after a minute of
  healthy recording; the disk guard stops every recording at 90 % and resumes below 85 %.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.modules.live.archive import SEGMENT_SECONDS, ArchiveDiskGuard, ArchiveStorage
from app.modules.live.services import RecordingSource

_log = logging.getLogger("live.recorder")

LEASE_TTL_S = 30
BACKOFF_FIRST_S = 5.0
BACKOFF_MAX_S = 300.0
HEALTHY_AFTER_S = 60.0

_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class Process(Protocol):
    def poll(self) -> int | None: ...
    def stop(self, timeout: float = 8.0) -> int: ...


class Sources(Protocol):
    def recording_sources(self) -> dict[int, RecordingSource]: ...


class RecorderLease:
    def __init__(self, redis: Any, owner: str, *, ttl_s: int = LEASE_TTL_S) -> None:
        self._redis = redis
        self._owner = owner
        self._ttl = ttl_s
        self._renew = redis.register_script(_RENEW)
        self._release = redis.register_script(_RELEASE)

    @staticmethod
    def key(channel_id: int) -> str:
        return f"live:recorder:{channel_id}"

    def acquire(self, channel_id: int) -> bool:
        return bool(self._redis.set(self.key(channel_id), self._owner, nx=True, ex=self._ttl))

    def renew(self, channel_id: int) -> bool:
        return bool(int(self._renew(keys=[self.key(channel_id)], args=[self._owner, self._ttl])))

    def release(self, channel_id: int) -> None:
        self._release(keys=[self.key(channel_id)], args=[self._owner])


def build_record_command(ffmpeg: str, source_url: str, channel_dir: Path, channel_id: int) -> list[str]:
    reconnect = (
        ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "10"]
        if source_url.startswith(("http://", "https://"))
        else []
    )
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-nostdin",
        *reconnect,
        "-rw_timeout",
        "15000000",
        "-i",
        source_url,
        # No -map: ffmpeg's default picks the best video and audio (the top rendition of an HLS
        # ladder); subtitles and data streams are dropped, they do not survive MPEG-TS copy well.
        "-sn",
        "-dn",
        "-c",
        "copy",
        "-metadata",
        f"neotv_record={channel_id}",
        # The HLS muxer, used as a segmenter: it names each segment by strftime at its start,
        # creates the day/hour folders, and writes through a .tmp file (temp_file) so a segment
        # appears under its final name only when complete. Nothing is deleted (no delete_segments):
        # retention does that. The rolling playlist it also writes is never served.
        "-f",
        "hls",
        "-hls_time",
        str(SEGMENT_SECONDS),
        "-hls_list_size",
        "3",
        "-hls_flags",
        "temp_file+program_date_time",
        "-hls_segment_type",
        "mpegts",
        "-strftime",
        "1",
        "-strftime_mkdir",
        "1",
        "-hls_segment_filename",
        str(channel_dir / "%Y%m%d" / "%H" / "%Y%m%dT%H%M%SZ.ts"),
        str(channel_dir / "recorder.m3u8"),
    ]


@dataclass
class _Recording:
    process: Process
    started: float


@dataclass
class _Backoff:
    failures: int = 0
    not_before: float = 0.0


@dataclass
class Recorder:
    sources: Sources
    storage: ArchiveStorage
    guard: ArchiveDiskGuard
    lease: RecorderLease
    spawn: Callable[[list[str]], Process]
    ffmpeg: str
    check_source: Callable[[str], None]  # raises when the egress policy refuses an external URL
    clock: Callable[[], float] = time.monotonic
    running: dict[int, _Recording] = field(default_factory=dict)
    backoff: dict[int, _Backoff] = field(default_factory=dict)

    def tick(self) -> None:
        """One supervision pass (every few seconds)."""
        allowed = self.guard.may_record()
        wanted = self.sources.recording_sources() if allowed else {}
        if not allowed and self.running:
            _log.warning("archive disk guard: recording stopped", extra={"channels": sorted(self.running)})
        now = self.clock()
        for channel_id in list(self.running):
            recording = self.running[channel_id]
            exited = recording.process.poll() is not None
            if channel_id not in wanted or exited or not self.lease.renew(channel_id):
                self._stop(channel_id, failed=exited and channel_id in wanted, ran=now - recording.started)
        for channel_id, source in wanted.items():
            if channel_id in self.running or self.backoff.get(channel_id, _Backoff()).not_before > now:
                continue
            if not self.lease.acquire(channel_id):
                continue  # another recorder has it
            try:
                if source.external:
                    self.check_source(source.url)
                directory = self.storage.channel_dir(channel_id)
                directory.mkdir(parents=True, exist_ok=True)
                process = self.spawn(build_record_command(self.ffmpeg, source.url, directory, channel_id))
            except Exception:
                _log.exception("recorder could not start", extra={"channel": channel_id})
                self.lease.release(channel_id)
                self._fail(channel_id, now)
                continue
            self.running[channel_id] = _Recording(process=process, started=now)
            _log.info("recording", extra={"channel": channel_id})

    def stop_all(self) -> None:
        for channel_id in list(self.running):
            self._stop(channel_id, failed=False, ran=0.0)

    def _stop(self, channel_id: int, *, failed: bool, ran: float) -> None:
        recording = self.running.pop(channel_id)
        recording.process.stop()
        self.lease.release(channel_id)
        if failed:
            _log.warning("recording ended", extra={"channel": channel_id, "ran_s": round(ran)})
            if ran >= HEALTHY_AFTER_S:
                self.backoff.pop(channel_id, None)  # it had been fine: start over from the first delay
            self._fail(channel_id, self.clock())

    def _fail(self, channel_id: int, now: float) -> None:
        state = self.backoff.setdefault(channel_id, _Backoff())
        delay = min(BACKOFF_FIRST_S * 2**state.failures, BACKOFF_MAX_S)
        state.failures += 1
        state.not_before = now + delay
