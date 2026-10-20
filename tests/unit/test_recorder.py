"""The catch-up recorder's supervision: leases, back-off, the disk guard, the egress check."""

from __future__ import annotations

from pathlib import Path

import fakeredis
import pytest

from app.modules.live.archive import LocalArchiveStorage
from app.modules.live.recorder import (
    BACKOFF_FIRST_S,
    HEALTHY_AFTER_S,
    Recorder,
    RecorderLease,
    build_record_command,
)
from app.modules.live.services import RecordingSource


class FakeProcess:
    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.code: int | None = None
        self.stopped = False

    def poll(self) -> int | None:
        return self.code

    def stop(self, timeout: float = 8.0) -> int:
        self.stopped = True
        return 0


class Guard:
    def __init__(self) -> None:
        self.ok = True

    def may_record(self) -> bool:
        return self.ok


class Sources:
    def __init__(self, **sources: RecordingSource) -> None:
        self.sources = {int(k.lstrip("c")): v for k, v in sources.items()}

    def recording_sources(self) -> dict[int, RecordingSource]:
        return dict(self.sources)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


EXTERNAL = RecordingSource("https://live.example.com/a.m3u8", external=True)
INGEST = RecordingSource("rtmp://rtmp:1935/live/abc", external=False)


@pytest.fixture
def redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis()


def _recorder(tmp_path: Path, redis: fakeredis.FakeRedis, sources: Sources, owner: str = "a", **kw: object) -> Recorder:
    spawned: list[FakeProcess] = []

    def spawn(argv: list[str]) -> FakeProcess:
        process = FakeProcess(argv)
        spawned.append(process)
        return process

    recorder = Recorder(
        sources=sources,
        storage=LocalArchiveStorage(tmp_path),
        guard=kw.pop("guard", Guard()),  # type: ignore[arg-type]
        lease=RecorderLease(redis, owner),
        spawn=spawn,
        ffmpeg="ffmpeg",
        check_source=kw.pop("check", lambda url: None),  # type: ignore[arg-type]
        clock=kw.pop("clock", Clock()),  # type: ignore[arg-type]
    )
    recorder.spawned = spawned  # type: ignore[attr-defined]
    return recorder


def test_records_every_archived_channel_once_across_replicas(tmp_path: Path, redis: fakeredis.FakeRedis) -> None:
    sources = Sources(c3=EXTERNAL, c4=INGEST)
    first, second = _recorder(tmp_path, redis, sources, "a"), _recorder(tmp_path, redis, sources, "b")
    first.tick()
    second.tick()
    assert sorted(first.running) == [3, 4] and second.running == {}  # the lease decides
    argv = first.running[3].process.argv  # type: ignore[attr-defined]
    assert argv[argv.index("-i") + 1] == EXTERNAL.url and argv[argv.index("-c") + 1] == "copy"
    assert argv[-1].endswith("3/recorder.m3u8") and "%Y%m%dT%H%M%SZ.ts" in argv[argv.index("-hls_segment_filename") + 1]

    first.stop_all()  # replica a goes away: its leases are released, b takes over
    second.tick()
    assert sorted(second.running) == [3, 4]


def test_a_channel_no_longer_archived_stops_and_frees_its_lease(tmp_path: Path, redis: fakeredis.FakeRedis) -> None:
    sources = Sources(c3=EXTERNAL)
    recorder = _recorder(tmp_path, redis, sources)
    recorder.tick()
    process = recorder.running[3].process
    sources.sources.clear()
    recorder.tick()
    assert recorder.running == {} and process.stopped  # type: ignore[attr-defined]
    assert redis.get(RecorderLease.key(3)) is None


def test_failures_back_off_and_a_healthy_run_resets_it(tmp_path: Path, redis: fakeredis.FakeRedis) -> None:
    clock = Clock()
    recorder = _recorder(tmp_path, redis, Sources(c3=EXTERNAL), clock=clock)
    recorder.tick()
    recorder.running[3].process.code = 1  # type: ignore[attr-defined]  # ffmpeg died at once
    recorder.tick()
    assert recorder.running == {} and recorder.backoff[3].not_before == clock.t + BACKOFF_FIRST_S
    clock.t += BACKOFF_FIRST_S - 1
    recorder.tick()
    assert recorder.running == {}  # still waiting
    clock.t += 1
    recorder.tick()
    recorder.running[3].process.code = 1  # type: ignore[attr-defined]
    recorder.tick()
    assert recorder.backoff[3].not_before == clock.t + 2 * BACKOFF_FIRST_S  # doubled
    clock.t += 2 * BACKOFF_FIRST_S
    recorder.tick()
    clock.t += HEALTHY_AFTER_S  # it then records fine for a minute before the source drops
    recorder.running[3].process.code = 0  # type: ignore[attr-defined]
    recorder.tick()
    assert recorder.backoff[3].not_before == clock.t + BACKOFF_FIRST_S  # back to the first delay


def test_the_disk_guard_stops_everything_and_recording_resumes(tmp_path: Path, redis: fakeredis.FakeRedis) -> None:
    guard = Guard()
    recorder = _recorder(tmp_path, redis, Sources(c3=EXTERNAL, c4=INGEST), guard=guard)
    recorder.tick()
    guard.ok = False
    recorder.tick()
    assert recorder.running == {}
    guard.ok = True
    recorder.tick()
    assert sorted(recorder.running) == [3, 4]


def test_only_external_urls_are_checked_and_a_refused_one_is_not_recorded(
    tmp_path: Path, redis: fakeredis.FakeRedis
) -> None:
    checked: list[str] = []

    def check(url: str) -> None:
        checked.append(url)
        raise PermissionError("non_public_ip")

    recorder = _recorder(tmp_path, redis, Sources(c3=EXTERNAL, c4=INGEST), check=check)
    recorder.tick()
    assert checked == [EXTERNAL.url] and list(recorder.running) == [4]
    assert 3 in recorder.backoff and redis.get(RecorderLease.key(3)) is None


def test_reconnect_options_only_for_http_sources() -> None:
    http = build_record_command("ffmpeg", EXTERNAL.url, Path("/a/3"), 3)
    rtmp = build_record_command("ffmpeg", INGEST.url, Path("/a/4"), 4)
    assert "-reconnect" in http and "-reconnect" not in rtmp
