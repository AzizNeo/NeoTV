"""Stream slots over time: when does a vanished client's slot come back?

A release normally arrives (in-app close, ``pagehide`` → ``sendBeacon``), but it is best effort: a
crash, a killed tab or a lost network sends nothing. Then the heartbeat window is the guarantee.
These tests pin that guarantee with a controlled clock, plus the invariant between the client's
heartbeat interval and the server's window (two constants in two files).
"""

from __future__ import annotations

import fakeredis
import pytest

from app.modules.playback import concurrency
from app.modules.playback.concurrency import StreamConcurrencyGuard
from app.modules.playback.services import HEARTBEAT_INTERVAL_S

USER = 7


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1_000_000.0]
    monkeypatch.setattr(concurrency.time, "time", lambda: now[0])
    return now


@pytest.fixture
def guard() -> StreamConcurrencyGuard:
    return StreamConcurrencyGuard(fakeredis.FakeRedis())


def _open(guard: StreamConcurrencyGuard, token: str, device: str) -> bool:
    return guard.acquire(user_id=USER, token=token, limit=1, device_key=device).granted


def test_a_vanished_clients_slot_comes_back_after_the_window(guard, clock):
    assert _open(guard, "tv-stream", "living-room-tv")
    # The TV crashes: no release, no heartbeat. Another device is refused while the window runs…
    clock[0] += guard.window - 1
    assert not _open(guard, "phone-stream", "phone")
    # …and admitted once it has passed: the slot was never stuck for good.
    clock[0] += 2
    assert _open(guard, "phone-stream", "phone")


def test_the_same_device_coming_back_never_waits(guard, clock):
    assert _open(guard, "before-crash", "laptop")
    clock[0] += 1  # the browser crashed and was reopened at once
    assert _open(guard, "after-crash", "laptop")  # replaces its own stale stream


def test_a_live_client_keeps_its_slot_far_beyond_the_window(guard, clock):
    assert _open(guard, "watching", "tv")
    for _ in range(30):  # five minutes of heartbeats
        clock[0] += HEARTBEAT_INTERVAL_S
        assert guard.heartbeat(user_id=USER, token="watching")
    assert not _open(guard, "intruder", "phone")


def test_a_client_survives_two_missed_heartbeats():
    """The window must outlast lost heartbeats (a mobile network hiccup, a busy tab) — at least
    two missed beats plus some jitter — or viewers get cut off mid-film. Raising the client's
    interval without the window (or shrinking the window) breaks this test, not production."""
    window = StreamConcurrencyGuard(fakeredis.FakeRedis()).window
    assert window > 3 * HEARTBEAT_INTERVAL_S, (window, HEARTBEAT_INTERVAL_S)
    assert window <= 60, "a vanished client should not hold a paid slot for more than a minute"
