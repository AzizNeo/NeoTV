"""Xtream stream URLs: a playback session under every rule, then a redirect to the signed proxy.

Apps cannot send heartbeats, so their sessions are kept alive by their own media requests: open
while the player fetches, ended like any other session (and then refused at the next request).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask

from app.kernel.container import resolve
from app.modules.playback.api import GrantVerifier, SessionInactiveError
from app.modules.playback.concurrency import StreamConcurrencyGuard
from app.modules.playback.grants import kept_alive_by_media
from app.modules.xtream.protocol import stream_id
from tests.support.client import Api, Reply

BASE = "/api/v1/xtream"
SERVER = "http://localhost:5173"


def _credential(api: Api, token: str, profile_id: int | None = None) -> tuple[str, str]:
    profile_id = profile_id or api.get("/api/v1/profiles", token=token).data[0]["id"]
    issued = api.post(f"{BASE}/credentials", token=token, json={"label": "TV", "profile_id": profile_id}).data
    return issued["credential"]["username"], issued["password"]


def _play(api: Api, creds: tuple[str, str], ref: str, section: str = "live", ext: str = "m3u8") -> Reply:
    return api.get(f"{BASE}/{section}/{creds[0]}/{creds[1]}/{stream_id(ref)}.{ext}")


def _grant(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def _active(api: Api, creds: tuple[str, str]) -> str:
    query = {"username": creds[0], "password": creds[1]}
    return str(api.get(f"{BASE}/player_api.php", query_string=query).body["user_info"]["active_cons"])


@pytest.fixture
def channels(api: Api, admin: str) -> dict[str, Any]:
    return {
        "news": api.channel(admin, "News", kind="live"),
        "sport": api.channel(admin, "Sport", kind="live"),
        "late": api.channel(admin, "Late", kind="live", rating="adult"),
    }


def test_a_stream_url_redirects_to_the_signed_proxy_never_the_origin(api: Api, channels: dict[str, Any]) -> None:
    creds = _credential(api, api.user("st1"))
    reply = _play(api, creds, channels["news"]["ref"])
    assert reply.status == 302 and reply.headers["Cache-Control"] == "no-store"
    location = reply.headers["Location"]
    assert location.startswith(f"{SERVER}/api/v1/playback/proxy?") and "cdn.example.com" not in location
    assert _active(api, creds) == "1"


def test_media_requests_keep_the_session_alive_and_an_ended_one_is_refused(
    app: Flask, api: Api, channels: dict[str, Any]
) -> None:
    creds = _credential(api, api.user("st2"))
    grant = _grant(_play(api, creds, channels["news"]["ref"]).headers["Location"])
    with app.app_context():
        guard = resolve(StreamConcurrencyGuard)
        verifier = resolve(GrantVerifier)
        media = verifier.verify(grant)  # what every proxied request does: check *and* refresh
        assert kept_alive_by_media(media.session_token) and guard.is_active(media.session_token)
        guard.release(media.session_token)  # ended (revoked device, admin, replaced …)
        with pytest.raises(SessionInactiveError):
            verifier.verify(grant)  # segments too, not only playlists: the player stops


def test_switching_channels_on_one_credential_replaces_the_stream(api: Api, channels: dict[str, Any]) -> None:
    creds = _credential(api, api.user("st3"))
    assert _play(api, creds, channels["news"]["ref"]).status == 302
    assert _play(api, creds, channels["sport"]["ref"]).status == 302  # same device: no second slot
    assert _active(api, creds) == "1"


def test_the_plans_stream_limit_holds_across_devices(api: Api, channels: dict[str, Any]) -> None:
    token = api.user("st4")  # free plan: one stream
    tv, phone = _credential(api, token), _credential(api, token)
    assert _play(api, tv, channels["news"]["ref"]).status == 302
    refused = _play(api, phone, channels["sport"]["ref"])
    assert (refused.status, refused.raw) == (429, b"STREAM_LIMIT_EXCEEDED")


def test_a_kids_credential_cannot_play_adult_content(api: Api, channels: dict[str, Any]) -> None:
    token = api.user("st5")
    assert api.post("/api/v1/billing/trial", token=token).status == 200
    kids = api.post("/api/v1/profiles", token=token, json={"name": "Kids", "is_kids": True}).data
    creds = _credential(api, token, kids["id"])
    refused = _play(api, creds, channels["late"]["ref"])
    assert (refused.status, refused.raw) == (403, b"CONTENT_NOT_ALLOWED_FOR_KIDS")
    assert _play(api, creds, channels["news"]["ref"]).status == 302


def test_refusals_say_why_in_one_word(api: Api, channels: dict[str, Any]) -> None:
    creds = _credential(api, api.user("st6"))
    ref = channels["news"]["ref"]
    assert _play(api, creds, ref, ext="ts").status == 415  # HLS only
    assert _play(api, ("a" * 10, "b" * 12), ref).status == 401
    assert api.get(f"{BASE}/live/{creds[0]}/{creds[1]}/abc.m3u8").status == 404
    assert api.get(f"{BASE}/live/{creds[0]}/{creds[1]}/99999991.m3u8").raw == b"CONTENT_NOT_FOUND"
    assert api.get(f"{BASE}/live/{creds[0]}/{creds[1]}/121").status == 415  # no extension
    assert _play(api, creds, ref, section="movie").status == 302  # the path groups, playback decides


def test_web_player_sessions_keep_their_heartbeat_contract(app: Flask, api: Api, channels: dict[str, Any]) -> None:
    viewer = api.user("st7")
    opened = api.open_session(viewer, channels["news"]["ref"]).data
    assert not kept_alive_by_media(opened["session_token"])
    with app.app_context():
        grant = _grant(opened["manifest_url"])
        segment = resolve(GrantVerifier).verify(grant)  # web sessions: segments do not touch the slot
        assert segment.session_token == opened["session_token"]


def test_an_address_that_keeps_guessing_is_refused_without_checking(
    app: Flask, api: Api, channels: dict[str, Any]
) -> None:
    from app.kernel.observability.metrics import Metrics
    from app.modules.xtream.guard import XtreamAuthGuard

    creds = _credential(api, api.user("st8"))
    guesser, neighbour = {"REMOTE_ADDR": "203.0.113.7"}, {"REMOTE_ADDR": "198.51.100.9"}
    wrong = {"username": creds[0], "password": "z" * 12}
    for _ in range(XtreamAuthGuard.MAX_FAILURES):
        reply = api.get(f"{BASE}/player_api.php", query_string=wrong, environ_base=guesser)
        assert reply.body == {"user_info": {"auth": 0}}
    right = {"username": creds[0], "password": creds[1]}
    blocked = api.get(f"{BASE}/player_api.php", query_string=right, environ_base=guesser)
    assert (blocked.status, blocked.body) == (429, {"user_info": {"auth": 0}})  # even the right password
    stream = api.get(
        f"{BASE}/live/{creds[0]}/{creds[1]}/{stream_id(channels['news']['ref'])}.m3u8", environ_base=guesser
    )
    assert (stream.status, stream.raw) == (429, b"TOO_MANY_FAILURES")
    assert api.get(f"{BASE}/xmltv.php", query_string=right, environ_base=guesser).status == 429
    # The owner's TV elsewhere is not locked out: the block is per address, never per credential.
    assert api.get(f"{BASE}/player_api.php", query_string=right, environ_base=neighbour).body["user_info"]["auth"] == 1
    with app.app_context():
        counts = {
            s.labels["result"]: s.value
            for family in resolve(Metrics).registry.collect()
            if family.name == "neotv_xtream_auth"
            for s in family.samples
            if s.name.endswith("_total")
        }
    assert counts["blocked"] >= 3 and counts["denied"] >= XtreamAuthGuard.MAX_FAILURES and counts["ok"] >= 1
