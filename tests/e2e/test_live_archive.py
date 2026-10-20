"""Catch-up archive settings (ADR-0012): opt-in per channel; external streams need the rights confirmed."""

from __future__ import annotations

from typing import Any

from tests.support.client import Api

ADMIN = "/api/v1/live/admin/channels"


def _channel(api: Api, admin: str, **body: Any) -> dict[str, Any]:
    reply = api.post(ADMIN, token=admin, json={"name": "Kanal", **body})
    assert reply.status == 201, reply.body
    return dict(reply.data["channel"])


def _archive(api: Api, admin: str, channel_id: int, **body: Any) -> Any:
    return api.put(f"{ADMIN}/{channel_id}/archive", token=admin, json=body)


def test_every_channel_starts_without_an_archive(api: Api, admin: str) -> None:
    channel = _channel(api, admin, source_type="ingest")
    assert (channel["archive_days"], channel["archive_confirmed_by"], channel["archive_confirmed_at"]) == (
        0,
        None,
        None,
    )


def test_own_channels_are_switched_on_by_the_administrator(api: Api, admin: str) -> None:
    admin_id = api.get("/api/v1/auth/me", token=admin).data["id"]
    channel = _channel(api, admin, source_type="ingest")
    on = _archive(api, admin, channel["id"], days=3)
    assert on.status == 200, on.body
    assert on.data["archive_days"] == 3 and on.data["archive_confirmed_by"] == admin_id
    assert on.data["archive_confirmed_at"] is not None
    assert _archive(api, admin, channel["id"], days=8).code == "ARCHIVE_INVALID"  # ARCHIVE_MAX_DAYS = 7
    assert _archive(api, admin, channel["id"], days=-1).status == 422
    off = _archive(api, admin, channel["id"], days=0).data
    assert (off["archive_days"], off["archive_confirmed_by"], off["archive_confirmed_at"]) == (0, None, None)


def test_recording_an_external_stream_needs_the_rights_confirmed(api: Api, admin: str) -> None:
    channel = _channel(api, admin, upstream_url="https://live.example.com/a.m3u8")
    assert _archive(api, admin, channel["id"], days=3).code == "ARCHIVE_RIGHTS_REQUIRED"
    assert _archive(api, admin, channel["id"], days=3, rights_confirmed=False).code == "ARCHIVE_RIGHTS_REQUIRED"
    on = _archive(api, admin, channel["id"], days=3, rights_confirmed=True)
    assert on.status == 200 and on.data["archive_days"] == 3


def test_a_new_source_url_turns_the_archive_off(api: Api, admin: str) -> None:
    channel = _channel(api, admin, upstream_url="https://live.example.com/a.m3u8")
    _archive(api, admin, channel["id"], days=7, rights_confirmed=True)
    renamed = api.patch(f"{ADMIN}/{channel['id']}", token=admin, json={"name": "Yeni ad"}).data
    assert renamed["archive_days"] == 7  # other edits keep it
    moved = api.patch(
        f"{ADMIN}/{channel['id']}", token=admin, json={"upstream_url": "https://other.example.com/b.m3u8"}
    )
    assert (moved.data["archive_days"], moved.data["archive_confirmed_by"]) == (0, None)  # confirmed for the old stream


def test_only_administrators_and_known_channels(api: Api, admin: str, viewer: str) -> None:
    channel = _channel(api, admin, source_type="ingest")
    assert _archive(api, viewer, channel["id"], days=3).code == "PERMISSION_DENIED"
    assert _archive(api, admin, 999_999, days=3).code == "LIVE_CHANNEL_NOT_FOUND"
    assert _archive(api, admin, channel["id"], days=3, extra=True).status == 422


def test_plans_carry_their_catch_up_window(api: Api) -> None:
    plans = {p["id"]: p["entitlements"]["catchup_days"] for p in api.get("/api/v1/billing/plans").data}
    assert plans == {"free": 0, "personal": 3, "duo": 3, "family": 7}


# ── retention and metrics (the recorder's output, faked as files) ──────────


def test_retention_keeps_each_window_and_drops_what_is_no_longer_archived(tmp_path: Any) -> None:
    from datetime import timedelta

    from app.kernel.container import resolve
    from app.kernel.observability.metrics import Metrics
    from app.kernel.time import utcnow
    from app.modules.live.archive import ArchiveStorage
    from app.modules.live.tasks import archive_retention
    from tests.support.factory import make_app

    app = make_app(archive_root=tmp_path)
    api = Api(app)
    admin = api.user("boss", role="admin")
    kept = _channel(api, admin, source_type="ingest")
    off = _channel(api, admin, source_type="ingest")
    _archive(api, admin, kept["id"], days=1)
    now = utcnow().replace(microsecond=0)
    with app.app_context():
        storage = resolve(ArchiveStorage)
        for channel_id, ages in ((kept["id"], (60, 3600, 2 * 86400)), (off["id"], (60,)), (999, (60,))):
            for age in ages:
                path = storage.channel_dir(channel_id) / storage.segment_name(now - timedelta(seconds=age))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"ts")
        result = archive_retention.apply().get()
        assert result == {"segments_removed": 3, "channels_trimmed": 1, "channels_dropped": 2}
        assert storage.channels() == [kept["id"]]  # switched off / removed: all gone
        assert storage.newest(kept["id"]) == now - timedelta(seconds=60)  # within the day: kept

        text = resolve(Metrics).render().decode()
    assert "neotv_archive_disk_used_ratio" in text
    lag = next(
        line for line in text.splitlines() if line.startswith(f'neotv_archive_lag_seconds{{channel="{kept["id"]}"}}')
    )
    assert 55 <= float(lag.split()[-1]) <= 120
    assert f'channel="{off["id"]}"' not in text  # only archived channels report


def test_the_recorder_is_given_only_what_can_be_recorded_now(app: Any, api: Api, admin: str) -> None:
    from app.kernel.container import resolve
    from app.kernel.db import db
    from app.modules.live.models import LiveChannel
    from app.modules.live.services import ArchiveService

    external = _channel(api, admin, upstream_url="https://live.example.com/a.m3u8")
    studio = _channel(api, admin, source_type="ingest")
    _channel(api, admin, upstream_url="https://live.example.com/not-archived.m3u8")
    _archive(api, admin, external["id"], days=3, rights_confirmed=True)
    _archive(api, admin, studio["id"], days=3)
    with app.app_context():
        sources = resolve(ArchiveService).recording_sources()
        assert sources[external["id"]].url == "https://live.example.com/a.m3u8" and sources[external["id"]].external
        assert studio["id"] not in sources  # the encoder is not connected: nothing to pull
        db.session.get(LiveChannel, studio["id"]).is_live = True
        db.session.commit()
        live = resolve(ArchiveService).recording_sources()[studio["id"]]
    assert live.url.endswith(f"/{studio['playback_id']}") and live.url.startswith("rtmp://") and not live.external
