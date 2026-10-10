"""Identity (stateless auth, rotating refresh) and profiles end to end."""

from __future__ import annotations

from tests.support.client import PASSWORD, Api

CSRF = {"X-Requested-With": "XMLHttpRequest"}


def test_register_login_me(api: Api) -> None:
    assert api.register("alice").status == 201
    assert api.register("alice").code == "USERNAME_TAKEN"
    login = api.login("alice")
    assert login.status == 200 and login.data["token_type"] == "Bearer"
    me = api.get("/api/v1/auth/me", token=login.data["access_token"])
    assert me.data["username"] == "alice"
    assert api.get("/api/v1/auth/me").code == "AUTH_REQUIRED"


def test_bad_credentials_and_weak_password(api: Api) -> None:
    api.register("bob")
    assert api.login("bob", "Wrong-Password1").status == 401
    assert api.register("weak", password="short").status == 422


def test_refresh_rotation_and_reuse_detection(api: Api) -> None:
    api.register("carol")
    api.login("carol")
    first_cookie = api.client.get_cookie("neotv_rt", path="/api/v1/auth")
    assert first_cookie is not None and first_cookie.http_only

    assert api.post("/api/v1/auth/refresh").code == "CSRF_HEADER_MISSING"
    rotated = api.post("/api/v1/auth/refresh", headers=CSRF)
    assert rotated.status == 200 and rotated.data["access_token"]

    # Replaying the *old* refresh token = theft signal → whole family revoked.
    api.client.set_cookie("neotv_rt", first_cookie.value, path="/api/v1/auth")
    assert api.post("/api/v1/auth/refresh", headers=CSRF).code == "REFRESH_REUSED"
    assert api.post("/api/v1/auth/refresh", headers=CSRF).status == 401


def test_password_change_invalidates_access_tokens(api: Api) -> None:
    token = api.user("dave")
    changed = api.post(
        "/api/v1/auth/change-password",
        token=token,
        json={"current_password": PASSWORD, "new_password": "Another-Secret7"},
    )
    assert changed.status in (200, 204)
    assert api.get("/api/v1/auth/me", token=token).status == 401  # token_version bumped
    assert api.login("dave", "Another-Secret7").status == 200


def test_default_profile_and_profile_context(api: Api) -> None:
    token = api.user("erin")
    profiles = api.get("/api/v1/profiles", token=token).data
    assert [p["is_default"] for p in profiles] == [True]
    # default_profile mode: no header → the default profile
    assert api.get("/api/v1/profiles/current", token=token).data["id"] == profiles[0]["id"]


def test_profile_limit_follows_plan_entitlements(api: Api) -> None:
    token = api.user("frank")
    assert (
        api.post("/api/v1/profiles", token=token, json={"name": "Kids", "is_kids": True}).code
        == "PROFILE_LIMIT_REACHED"
    )
    assert api.post("/api/v1/billing/trial", token=token).status == 200  # family: 5 profiles
    kids = api.post("/api/v1/profiles", token=token, json={"name": "Kids", "is_kids": True})
    assert kids.status == 201
    selected = api.post(f"/api/v1/profiles/{kids.data['id']}/select", token=token, json={})
    header = {"X-Profile-Token": selected.data["profile_token"]}
    assert api.get("/api/v1/profiles/current", token=token, headers=header).data["is_kids"] is True


def test_profile_pin_protects_selection(api: Api) -> None:
    token = api.user("gina")
    api.post("/api/v1/billing/trial", token=token)
    profile = api.post("/api/v1/profiles", token=token, json={"name": "Parent"}).data
    assert api.put(f"/api/v1/profiles/{profile['id']}/pin", token=token, json={"pin": "1234"}).status == 200
    assert api.post(f"/api/v1/profiles/{profile['id']}/select", token=token, json={}).code == "PIN_REQUIRED"
    assert api.post(f"/api/v1/profiles/{profile['id']}/select", token=token, json={"pin": "0000"}).code == "PIN_INVALID"
    assert api.post(f"/api/v1/profiles/{profile['id']}/select", token=token, json={"pin": "1234"}).status == 200


def test_profiles_are_owner_scoped(api: Api) -> None:
    owner = api.user("henry")
    other = api.user("ivan")
    profile_id = api.get("/api/v1/profiles", token=owner).data[0]["id"]
    assert api.post(f"/api/v1/profiles/{profile_id}/select", token=other, json={}).code == "PROFILE_NOT_FOUND"
    forged = api.post(f"/api/v1/profiles/{profile_id}/select", token=owner, json={}).data["profile_token"]
    reply = api.get("/api/v1/profiles/current", token=other, headers={"X-Profile-Token": forged})
    assert reply.status in (401, 403)


def test_devices_are_tracked_from_login_events(api: Api) -> None:
    token = api.user("judy")
    devices = api.get("/api/v1/devices", token=token).data
    assert len(devices) == 1 and devices[0]["is_current"] is True
    assert api.delete(f"/api/v1/devices/{devices[0]['id']}", token=token).status == 204
    # the revoked device's refresh tokens are gone (identity consumer of devices.device_revoked)
    assert api.post("/api/v1/auth/refresh", headers=CSRF).status == 401
