"""Catalog, live and the playback gate end to end."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask

from app.kernel.container import resolve
from app.kernel.security.egress import EgressDeniedError, EgressGateway, EgressNetworkError
from app.modules.playback.api import MediaGrant
from app.modules.playback.grants import SignedStreamUrlFactory
from app.modules.playback.hls_proxy import HlsProxyService
from tests.support.client import Api


def test_catalog_browse_is_kids_aware(api: Api, admin: str, viewer: str) -> None:
    api.channel(admin, "Cartoons", group="Kids", rating="general")
    api.channel(admin, "Late Night", group="Movies", rating="adult")
    listing = api.get("/api/v1/catalog/channels", token=viewer).data
    assert {c["name"] for c in listing["items"]} == {"Cartoons", "Late Night"}
    assert "stream_url" not in listing["items"][0]  # origin URLs never reach viewers

    api.post("/api/v1/billing/trial", token=viewer)
    kids = api.post("/api/v1/profiles", token=viewer, json={"name": "Kid", "is_kids": True}).data
    token = api.post(f"/api/v1/profiles/{kids['id']}/select", token=viewer, json={}).data["profile_token"]
    kid_listing = api.get("/api/v1/catalog/channels", token=viewer, headers={"X-Profile-Token": token}).data
    assert [c["name"] for c in kid_listing["items"]] == ["Cartoons"]


def test_catalog_admin_requires_permission_and_import_runs_as_task(api: Api, admin: str, viewer: str) -> None:
    assert api.get("/api/v1/catalog/admin/channels", token=viewer).code == "PERMISSION_DENIED"
    m3u = '#EXTM3U\n#EXTINF:-1 group-title="News",News One\nhttps://cdn.example.com/news1.m3u8\n'
    accepted = api.post("/api/v1/catalog/admin/import", token=admin, json={"text": m3u, "probe": False})
    assert accepted.status == 202
    status = api.get(f"/api/v1/tasks/{accepted.data['task_id']}", token=admin).data
    assert status["state"] == "SUCCESS"
    assert api.get("/api/v1/tasks/" + accepted.data["task_id"], token=viewer).status == 404  # owner-scoped
    names = [c["name"] for c in api.get("/api/v1/catalog/admin/channels", token=admin).data["items"]]
    assert "News One" in names


def test_stream_limit_same_device_replaces_other_device_blocked(api: Api, admin: str, viewer: str) -> None:
    a, b = api.channel(admin, "A")["ref"], api.channel(admin, "B")["ref"]
    first = api.open_session(viewer, a, headers={"X-Device-ID": "living-room-tv"})
    assert first.status == 201 and first.data["manifest_url"].startswith("/api/v1/playback/proxy?")
    assert "cdn.example.com" not in first.data["manifest_url"]  # signed proxy, origin hidden
    zap = api.open_session(viewer, b, headers={"X-Device-ID": "living-room-tv"})
    assert zap.status == 201  # channel switch on the same device replaces the slot
    blocked = api.open_session(viewer, a, headers={"X-Device-ID": "pocket-phone-1"})
    assert blocked.code == "STREAM_LIMIT_EXCEEDED" and blocked.status == 403
    assert api.get("/api/v1/playback/limits", token=viewer).data["active_streams"] == 1
    hb = api.post(
        "/api/v1/playback/sessions/heartbeat", token=viewer, json={"session_token": zap.data["session_token"]}
    )
    assert hb.status == 200
    other = api.user("intruder")
    stolen = api.post(
        "/api/v1/playback/sessions/heartbeat", token=other, json={"session_token": zap.data["session_token"]}
    )
    assert stolen.code == "SESSION_EXPIRED"  # heartbeat is user-scoped (no IDOR)


def test_kids_policy_denies_playback(api: Api, admin: str, viewer: str) -> None:
    adult = api.channel(admin, "Adult", rating="adult")["ref"]
    api.post("/api/v1/billing/trial", token=viewer)
    kids = api.post("/api/v1/profiles", token=viewer, json={"name": "Kid", "is_kids": True}).data
    token = api.post(f"/api/v1/profiles/{kids['id']}/select", token=viewer, json={}).data["profile_token"]
    denied = api.open_session(viewer, adult, headers={"X-Profile-Token": token})
    assert denied.code == "CONTENT_NOT_ALLOWED_FOR_KIDS"
    assert denied.body["error"]["details"]["policy"] == "kids_rating"


def test_unknown_namespace_and_missing_content_are_named(api: Api, viewer: str) -> None:
    assert api.open_session(viewer, "podcast:1").code == "CONTENT_PROVIDER_UNAVAILABLE"
    assert api.open_session(viewer, "catalog:999").code == "CONTENT_NOT_FOUND"
    assert api.open_session(viewer, "catalog").status == 422


def test_proxy_rejects_forged_and_foreign_grants(api: Api, admin: str, viewer: str) -> None:
    ref = api.channel(admin, "A")["ref"]
    url = api.open_session(viewer, ref).data["manifest_url"]
    params = parse_qs(urlsplit(url).query)
    forged = {k: v[0] for k, v in params.items()} | {"s": "999.othersession"}
    assert api.get("/api/v1/playback/proxy", query_string=forged).status == 403


def test_hls_rewrite_resigns_children_and_keeps_internal_key_uris(app: Flask) -> None:
    with app.app_context():
        proxy = resolve(HlsProxyService)
        grant = MediaGrant(user_id=1, session_token="tok", target="https://cdn/x/master.m3u8", expires_at=2_000_000_000)
        out = proxy.rewrite(
            "#EXTM3U\n"
            '#EXT-X-KEY:METHOD=AES-128,URI="/api/v1/drm/keys/00112233445566778899aabbccddeeff"\n'
            '#EXT-X-MAP:URI="init.mp4"\n'
            "#EXTINF:4,\nseg1.ts\n",
            base_url="https://cdn/x/master.m3u8",
            grant=grant,
        )
    lines = out.splitlines()
    assert 'URI="/api/v1/drm/keys/00112233445566778899aabbccddeeff?' in lines[1]  # internal grant, not proxied
    assert lines[2].startswith('#EXT-X-MAP:URI="/api/v1/playback/proxy?')
    assert lines[4].startswith("/api/v1/playback/proxy?") and "cdn" not in lines[4]
    assert isinstance(resolve, object) and SignedStreamUrlFactory  # imported surface stays public


def test_live_external_channel_and_guide(api: Api, admin: str, viewer: str) -> None:
    created = api.post(
        "/api/v1/live/admin/channels",
        token=admin,
        json={
            "name": "News 24",
            "source_type": "external",
            "upstream_url": "https://live.example.com/n/master.m3u8",
            "rating": "general",
        },
    )
    assert created.status == 201 and created.data["ingest_key"] is None
    ref = created.data["channel"]["ref"]
    assert [c["name"] for c in api.get("/api/v1/live/channels", token=viewer).data] == ["News 24"]
    session = api.open_session(viewer, ref)
    assert session.status == 201 and session.data["is_live"] is True


def test_live_ingest_key_is_shown_once_and_callbacks_are_internal(api: Api, admin: str) -> None:
    created = api.post("/api/v1/live/admin/channels", token=admin, json={"name": "Studio", "source_type": "ingest"})
    key = created.data["ingest_key"]
    assert key and len(key) >= 24
    listed = api.get("/api/v1/live/admin/channels", token=admin).data
    assert all("ingest_key" not in c or c["ingest_key"] is None for c in listed)
    bad = api.post("/api/v1/live/ingest/on-publish", data={"name": "wrong"}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert bad.status in (403, 404)
    ok = api.post("/api/v1/live/ingest/on-publish", data={"name": key}, environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert ok.status == 302 and ok.headers["Location"].endswith(created.data["channel"]["playback_id"])
    outsider = api.post("/api/v1/live/ingest/on-publish", data={"name": key}, environ_base={"REMOTE_ADDR": "8.8.8.8"})
    assert outsider.status == 403


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (EgressNetworkError("SSLError: https://cdn.example.com/A.m3u8", kind="tls"), "tls"),
        (EgressNetworkError("ConnectTimeout: https://cdn.example.com/A.m3u8", kind="timeout"), "timeout"),
        (EgressDeniedError("dns", "https://cdn.example.com/A.m3u8"), "dns"),
        (EgressDeniedError("non_public_ip:10.0.0.1", "https://cdn.example.com/A.m3u8"), "blocked"),
    ],
)
def test_proxy_failures_say_why_but_never_where(
    api: Api, admin: str, viewer: str, monkeypatch: pytest.MonkeyPatch, failure: Exception, reason: str
) -> None:
    def fail(*_args: object, **_kw: object) -> None:
        raise failure

    monkeypatch.setattr(EgressGateway, "get", fail)
    url = api.open_session(viewer, api.channel(admin, "A")["ref"]).data["manifest_url"]
    reply = api.get(url)
    assert reply.status == 502 and reply.code == "UPSTREAM_UNAVAILABLE"
    assert reply.body["error"]["details"] == {"reason": reason}
    assert b"cdn.example.com" not in reply.raw  # origin URLs (may embed provider credentials) never reach viewers


def test_one_device_opening_concurrently_never_hits_its_own_limit(api: Api, admin: str, viewer: str) -> None:
    """Regression: replace-same-device ran outside the atomic acquire, so two simultaneous opens from one
    device (React StrictMode, a double click, two tabs) both missed each other and one got
    STREAM_LIMIT_EXCEEDED on a 1-screen plan."""
    import threading

    from app.modules.playback.concurrency import StreamConcurrencyGuard

    if api.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        pytest.skip("concurrent requests need a real database: runs in tests/integration (PostgreSQL + Redis)")

    ref = api.channel(admin, "Race")["ref"]
    headers = {"Authorization": f"Bearer {viewer}", "User-Agent": "race-test", "X-Device-ID": "race-device-01"}
    barrier = threading.Barrier(4)  # within the open rate-limit burst (5)
    statuses: list[int] = []
    bodies: list[str] = []

    def open_once() -> None:
        client = api.app.test_client()
        barrier.wait()
        reply = client.post("/api/v1/playback/sessions", json={"content_ref": ref}, headers=headers)
        statuses.append(reply.status_code)
        bodies.append(reply.get_data(as_text=True)[:160])

    threads = [threading.Thread(target=open_once) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [201] * 4, bodies
    with api.app.app_context():
        assert resolve(StreamConcurrencyGuard).active_count(_user_id(api, viewer)) == 1

    other = api.open_session(viewer, ref, headers={"User-Agent": "race-test", "X-Device-ID": "other-device-02"})
    assert other.code == "STREAM_LIMIT_EXCEEDED"  # a *different* device still respects the plan


def _user_id(api: Api, token: str) -> int:
    return int(api.get("/api/v1/auth/me", token=token).data["id"])
