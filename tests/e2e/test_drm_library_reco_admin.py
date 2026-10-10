"""DRM, library, recommendations and admin end to end."""

from __future__ import annotations

import base64
import json
from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from flask import Flask

from app.kernel.db import db
from app.modules.playback.models import PlaybackSessionRecord
from tests.support.client import Api


def _kid_b64(key_id: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(key_id)).decode().rstrip("=")


def _uid(api: Api, token: str) -> int:
    return int(api.get("/api/v1/auth/me", token=token).data["id"])


# ── DRM ────────────────────────────────────────────────────────────────────


@pytest.fixture
def protected(api: Api, admin: str) -> dict[str, str]:
    ref = api.channel(admin, "Film")["ref"]
    content = api.post(
        "/api/v1/drm/admin/contents",
        token=admin,
        json={"content_ref": ref, "systems": ["aes-128", "clearkey", "widevine"]},
    ).data
    key = api.get(f"/api/v1/drm/admin/contents/{content['id']}/key", token=admin)
    assert key.headers["Cache-Control"].startswith("no-store")
    return {"ref": ref, "id": str(content["id"]), "key_id": content["key_id"], "key_hex": key.data["key_hex"]}


def test_drm_admin_contracts(api: Api, admin: str, viewer: str, protected: dict[str, str]) -> None:
    assert (
        api.post(
            "/api/v1/drm/admin/contents", token=admin, json={"content_ref": protected["ref"], "systems": ["aes-128"]}
        ).code
        == "DRM_ALREADY_PROTECTED"
    )
    assert (
        api.post(
            "/api/v1/drm/admin/contents", token=admin, json={"content_ref": "catalog:999", "systems": ["aes-128"]}
        ).code
        == "DRM_UNKNOWN_CONTENT"
    )
    assert api.get("/api/v1/drm/admin/contents", token=viewer).code == "PERMISSION_DENIED"


def test_key_delivery_and_clearkey_are_session_bound(
    api: Api, admin: str, viewer: str, protected: dict[str, str]
) -> None:
    session = api.open_session(viewer, protected["ref"]).data
    drm = session["drm"]
    assert drm["systems"] == "aes-128,clearkey"  # widevine enabled but no issuer installed → not offered
    assert drm["max_resolution"] == "480p"  # free plan ceiling applied

    key = api.get(drm["aes-128.key_uri"])
    assert key.status == 200 and key.raw.hex() == protected["key_hex"]
    query = urlsplit(drm["aes-128.key_uri"]).query
    assert api.get(f"/api/v1/drm/keys/{'a' * 32}?{query}").status == 403  # grant covers one key only

    challenge = json.dumps({"kids": [_kid_b64(protected["key_id"])]}).encode()
    licence = api.post(drm["clearkey.license_url"], data=challenge)
    assert licence.status == 200 and licence.body["keys"][0]["kid"] == _kid_b64(protected["key_id"])
    bad = api.post(drm["clearkey.license_url"], data=json.dumps({"kids": ["AAAA"]}).encode())
    assert bad.code == "DRM_CHALLENGE_INVALID"

    active = api.get("/api/v1/drm/admin/licenses/active", token=admin).data
    assert {lic["system"] for lic in active} == {"aes-128", "clearkey"}
    api.post("/api/v1/playback/sessions/release", json={"session_token": session["session_token"]})
    assert api.get(drm["aes-128.key_uri"]).code == "SESSION_INACTIVE"
    assert api.get("/api/v1/drm/admin/licenses/active", token=admin).data == []  # released via event

    stats = api.get("/api/v1/drm/admin/stats", token=admin).data
    assert stats["issued_24h"] == 2 and stats["denied_24h"] == 1 and stats["keys_delivered_24h"] == 1


def test_key_rotation_revokes_and_removal_shreds(api: Api, admin: str, viewer: str, protected: dict[str, str]) -> None:
    session = api.open_session(viewer, protected["ref"]).data
    assert api.get(session["drm"]["aes-128.key_uri"]).status == 200
    rotated = api.post(f"/api/v1/drm/admin/contents/{protected['id']}/rotate-key", token=admin).data
    assert rotated["key_id"] != protected["key_id"] and rotated["active_licenses"] == 0
    channel_id = protected["ref"].split(":")[1]
    assert api.delete(f"/api/v1/catalog/admin/channels/{channel_id}", token=admin).status == 204
    assert api.get("/api/v1/drm/admin/contents", token=admin).data["total"] == 0  # ContentRemoved consumer


def test_device_class_policy(api: Api, admin: str, viewer: str) -> None:
    ref = api.channel(admin, "TV only")["ref"]
    policy = api.post(
        "/api/v1/drm/admin/policies", token=admin, json={"name": "tv-only", "allowed_device_classes": ["tv"]}
    ).data
    api.post(
        "/api/v1/drm/admin/contents",
        token=admin,
        json={"content_ref": ref, "systems": ["aes-128"], "policy_id": policy["id"]},
    )
    denied = api.open_session(viewer, ref)
    assert denied.code == "DEVICE_CLASS_NOT_ALLOWED"
    tv = api.open_session(viewer, ref, headers={"User-Agent": "Mozilla/5.0 (Web0S; Linux/SmartTV)"})
    assert tv.status == 201
    assert api.delete(f"/api/v1/drm/admin/policies/{policy['id']}", token=admin).code == "DRM_POLICY_IN_USE"


# ── library / recommendations ──────────────────────────────────────────────


def _watch(api: Api, app: Flask, token: str, ref: str, minutes: int = 5) -> None:
    session = api.open_session(token, ref).data
    with app.app_context():
        record = db.session.get(PlaybackSessionRecord, session["session_token"])
        record.started_at -= timedelta(minutes=minutes)
        db.session.commit()
    api.post("/api/v1/playback/sessions/release", json={"session_token": session["session_token"]})


def test_library_flows(api: Api, app: Flask, admin: str, viewer: str) -> None:
    news = api.channel(admin, "News", group="News")["ref"]
    film = api.channel(admin, "Film", group="Movies", rating="adult")["ref"]
    assert api.put(f"/api/v1/library/favorites/{news}", token=viewer).status == 200
    assert api.put(f"/api/v1/library/favorites/{news}", token=viewer).status == 200  # idempotent
    assert api.put("/api/v1/library/favorites/catalog:999", token=viewer).code == "LIBRARY_CONTENT_NOT_FOUND"
    assert api.put("/api/v1/library/favorites/garbage", token=viewer).code == "INVALID_CONTENT_REF"
    assert api.get("/api/v1/library/favorites/refs", token=viewer).data == [news]

    api.put(f"/api/v1/library/progress/{film}", token=viewer, json={"position_s": 600, "duration_s": 3600})
    progress = api.get(f"/api/v1/library/progress/{film}", token=viewer).data
    assert (progress["position_s"], progress["progress_percent"], progress["completed"]) == (600, 17, False)
    assert [i["content"]["ref"] for i in api.get("/api/v1/library/continue", token=viewer).data] == [film]
    api.put(f"/api/v1/library/progress/{film}", token=viewer, json={"position_s": 3500, "duration_s": 3600})
    assert api.get("/api/v1/library/continue", token=viewer).data == []  # completed

    _watch(api, app, viewer, news)
    history = api.get("/api/v1/library/history", token=viewer).data
    assert history[0]["content"]["ref"] == news and history[0]["watched_seconds"] >= 290
    assert api.delete(f"/api/v1/library/favorites/{news}", token=viewer).status == 204
    assert api.delete("/api/v1/library/history", token=viewer).data["deleted"] == 1


def test_library_is_profile_scoped_and_purged_with_content(api: Api, admin: str, viewer: str) -> None:
    ref = api.channel(admin, "News")["ref"]
    api.put(f"/api/v1/library/favorites/{ref}", token=viewer)
    other = api.user("other")
    assert api.get("/api/v1/library/favorites/refs", token=other).data == []
    api.delete(f"/api/v1/catalog/admin/channels/{ref.split(':')[1]}", token=admin)
    assert api.get("/api/v1/library/favorites/refs", token=viewer).data == []


def test_recommendation_rows(api: Api, app: Flask, admin: str, viewer: str) -> None:
    watched = api.channel(admin, "News 1", group="News")["ref"]
    candidate = api.channel(admin, "News 2", group="News")["ref"]
    api.channel(admin, "Cartoon", group="Kids")
    _watch(api, app, viewer, watched)
    trending = api.get("/api/v1/recommendations/trending", token=viewer).data
    assert [i["ref"] for i in trending["items"]] == [watched]
    for_you = api.get("/api/v1/recommendations/for-you", token=viewer).data
    assert for_you["items"][0]["ref"] == candidate and for_you["items"][0]["reason"] == "Because you like News"
    home = api.get("/api/v1/recommendations/home", token=viewer).data
    assert home[0]["key"] == "for_you" and home[-1]["key"] == "trending"


# ── admin ──────────────────────────────────────────────────────────────────


def test_admin_dashboard_users_sessions(api: Api, admin: str, viewer: str) -> None:
    assert api.get("/api/v1/admin/stats", token=viewer).code == "PERMISSION_DENIED"
    stats = api.get("/api/v1/admin/stats", token=admin).data
    assert stats["users"]["total"] == 2 and stats["plans"]["free"] == 2 and stats["drm"] is not None
    ref = api.channel(admin, "Live A")["ref"]
    session = api.open_session(viewer, ref).data
    users = {u["username"]: u for u in api.get("/api/v1/admin/users", token=admin).data["items"]}
    assert users["viewer1"]["active_sessions"] == 1 and users["viewer1"]["plan"] == "free"

    viewer_id = _uid(api, viewer)
    assert api.post(f"/api/v1/admin/users/{viewer_id}/suspend", token=admin).data["is_active"] is False
    assert api.get("/api/v1/admin/sessions/live", token=admin).data == []  # streams ended via event
    assert (
        api.post(
            "/api/v1/playback/sessions/heartbeat", token=viewer, json={"session_token": session["session_token"]}
        ).status
        == 401
    )
    admin_id = _uid(api, admin)
    assert api.post(f"/api/v1/admin/users/{admin_id}/suspend", token=admin).code == "PROTECTED_ACCOUNT"


def test_abuse_flags(api: Api, app: Flask, admin: str) -> None:
    api.register("sharer")
    for i in range(6):
        api.login("sharer", environ_base={"REMOTE_ADDR": f"8.8.8.{i}"})
    with app.app_context():
        from app.kernel.container import resolve
        from app.modules.admin.services import AbuseService

        assert resolve(AbuseService).evaluate() == 1
        assert resolve(AbuseService).evaluate() == 1  # updates the open flag, never duplicates
    flags = api.get("/api/v1/admin/abuse/flags", token=admin).data
    assert len(flags) == 1 and flags[0]["kind"] == "many_ips" and flags[0]["score"] >= 6
    resolved = api.post(
        f"/api/v1/admin/abuse/flags/{flags[0]['id']}/resolve", token=admin, json={"outcome": "dismissed"}
    )
    assert resolved.data["status"] == "dismissed"
    assert api.get("/api/v1/admin/abuse/flags", token=admin).data == []
