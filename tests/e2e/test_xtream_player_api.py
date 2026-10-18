"""player_api.php as an Xtream app sees it: login, server info and live lists, with exact JSON types.

Apps parse these answers strictly (numbers as strings in some fields, real numbers in others), so the
types are part of the contract and asserted field by field.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.xtream.protocol import OWN_LIVE_CATEGORY, content_ref, stream_id
from tests.support.client import Api, Reply

PLAYER = "/api/v1/xtream/player_api.php"  # nginx serves it as <server>/player_api.php

#: Field → JSON type an Xtream app expects (str for "numbers as text").
LIVE_STREAM_TYPES: dict[str, type | tuple[type, ...]] = {
    "num": int,
    "name": str,
    "stream_type": str,
    "stream_id": int,
    "stream_icon": str,
    "epg_channel_id": (str, type(None)),
    "added": str,
    "is_adult": str,
    "category_id": str,
    "category_ids": list,
    "custom_sid": str,
    "tv_archive": int,
    "direct_source": str,
    "tv_archive_duration": int,
}
USER_INFO_TYPES: dict[str, type | tuple[type, ...]] = {
    "username": str,
    "password": str,
    "message": str,
    "auth": int,
    "status": str,
    "exp_date": (str, type(None)),
    "is_trial": str,
    "active_cons": str,
    "created_at": str,
    "max_connections": str,
    "allowed_output_formats": list,
}


def _shape(item: dict[str, Any], types: dict[str, type | tuple[type, ...]]) -> None:
    assert set(item) == set(types), set(item) ^ set(types)
    for field, expected in types.items():
        assert isinstance(item[field], expected) and not isinstance(item[field], bool), (field, item[field])


def _credential(api: Api, token: str, profile_id: int | None = None) -> tuple[str, str]:
    profile_id = profile_id or api.get("/api/v1/profiles", token=token).data[0]["id"]
    issued = api.post("/api/v1/xtream/credentials", token=token, json={"label": "TV", "profile_id": profile_id}).data
    return issued["credential"]["username"], issued["password"]


def _call(api: Api, creds: tuple[str, str], action: str | None = None, **params: str) -> Reply:
    query = {"username": creds[0], "password": creds[1], **({"action": action} if action else {}), **params}
    return api.get(PLAYER, query_string=query)


@pytest.fixture
def lineup(api: Api, admin: str) -> dict[str, Any]:
    news = api.channel(admin, "News One", group="Haber", kind="live")
    kids = api.channel(admin, "Cartoons", group="Çocuk", kind="live")
    late = api.channel(admin, "Late Night", group="Haber", rating="adult", kind="live")
    api.channel(admin, "A Movie", group="Film", kind="vod")  # VOD never shows among live streams
    own = api.post(
        "/api/v1/live/admin/channels",
        token=admin,
        json={
            "name": "Studio",
            "source_type": "external",
            "upstream_url": "https://live.example.com/s.m3u8",
            "rating": "general",
        },
    )
    assert own.status == 201, own.body
    return {"news": news, "kids": kids, "late": late, "own": own.data["channel"]}


def test_login_answers_user_and_server_info_with_exact_types(api: Api) -> None:
    token = api.user("tv1")
    creds = _credential(api, token)
    reply = _call(api, creds)
    assert reply.status == 200 and reply.headers["Content-Type"].startswith("application/json")
    assert reply.headers["Cache-Control"] == "no-store"
    assert "success" not in reply.body  # the protocol's bare JSON, not NeoTV's envelope
    info = reply.body["user_info"]
    _shape(info, USER_INFO_TYPES)
    assert (info["username"], info["password"], info["auth"], info["status"]) == (*creds, 1, "Active")
    assert info["allowed_output_formats"] == ["m3u8"] and info["max_connections"] == "1"  # free plan: one stream
    server = reply.body["server_info"]
    assert server["url"] == "localhost" and server["port"] == "5173" and server["server_protocol"] == "http"
    assert isinstance(server["timestamp_now"], int) and server["timezone"] == "UTC"


def test_form_posted_credentials_work_too(api: Api) -> None:
    creds = _credential(api, api.user("tv2"))
    reply = api.post(PLAYER, data={"username": creds[0], "password": creds[1]})
    assert reply.status == 200 and reply.body["user_info"]["auth"] == 1


@pytest.mark.parametrize("action", [None, "get_live_streams"])
def test_wrong_credentials_get_the_protocols_one_refusal(api: Api, action: str | None) -> None:
    username, _ = _credential(api, api.user("tv3"))
    reply = _call(api, (username, "x" * 12), action)
    assert reply.body == {"user_info": {"auth": 0}}
    assert reply.status == (200 if action is None else 401)  # login probe vs data request
    assert api.get(PLAYER).body == {"user_info": {"auth": 0}}  # nothing at all


def test_live_categories_and_streams(api: Api, lineup: dict[str, Any]) -> None:
    creds = _credential(api, api.user("tv4"))
    categories = _call(api, creds, "get_live_categories").body
    assert {c["category_name"] for c in categories} == {"Haber", "Çocuk", OWN_LIVE_CATEGORY}
    assert categories[-1]["category_name"] == OWN_LIVE_CATEGORY  # catalogue groups first (database collation)
    for c in categories:
        assert set(c) == {"category_id", "category_name", "parent_id"}
        assert c["category_id"].isdigit() and c["parent_id"] == 0
    by_name = {c["category_name"]: c["category_id"] for c in categories}

    streams = _call(api, creds, "get_live_streams").body
    for item in streams:
        _shape(item, LIVE_STREAM_TYPES)
    assert [s["num"] for s in streams] == list(range(1, len(streams) + 1))
    names = {s["name"]: s for s in streams}
    assert set(names) == {"News One", "Late Night", "Cartoons", "Studio"}  # an adult profile sees all; no VOD
    assert names["Late Night"]["is_adult"] == "1" and names["News One"]["is_adult"] == "0"
    assert names["Studio"]["category_id"] == by_name[OWN_LIVE_CATEGORY]
    assert names["News One"]["stream_id"] == stream_id(lineup["news"]["ref"])
    assert all(s["direct_source"] == "" for s in streams)  # the origin never leaves the server
    assert "cdn.example.com" not in str(streams) and "live.example.com" not in str(streams)

    haber = _call(api, creds, "get_live_streams", category_id=by_name["Haber"]).body
    assert {s["name"] for s in haber} == {"News One", "Late Night"}
    assert _call(api, creds, "get_live_streams", category_id="999999").body == []


def test_category_ids_are_stable_across_calls_and_accounts(api: Api, lineup: dict[str, Any]) -> None:
    first = _call(api, _credential(api, api.user("tv5")), "get_live_categories").body
    again = _call(api, _credential(api, api.user("tv6")), "get_live_categories").body
    assert first == again


def test_a_kids_credential_lists_kids_content_only(api: Api, lineup: dict[str, Any]) -> None:
    token = api.user("tv7")
    assert api.post("/api/v1/billing/trial", token=token).status == 200
    kids = api.post("/api/v1/profiles", token=token, json={"name": "Kids", "is_kids": True}).data
    creds = _credential(api, token, kids["id"])
    names = {s["name"] for s in _call(api, creds, "get_live_streams").body}
    assert "Late Night" not in names and {"News One", "Cartoons", "Studio"} <= names


def test_unknown_and_pending_actions_answer_an_empty_list(api: Api) -> None:
    creds = _credential(api, api.user("tv8"))
    assert _call(api, creds, "no_such_action").body == []


def test_stream_ids_round_trip_and_reject_garbage() -> None:
    assert stream_id("catalog:12") == 121 and stream_id("live:3") == 32
    assert str(content_ref(121)) == "catalog:12" and str(content_ref("32")) == "live:3"
    for garbage in ("", "abc", "-11", "10", "19", "1" * 19, 125):
        assert content_ref(garbage) is None, garbage
