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
