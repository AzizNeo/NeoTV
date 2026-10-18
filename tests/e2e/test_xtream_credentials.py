"""xtream app credentials end to end: issue (shown once), list, revoke, and what ends them.

A credential is what a TV app (an Xtream Codes client) sends on every request, so it must never be the
account password, must work only for the profile it was made for, and must stop at once when the
owner revokes it, changes the password, deletes the profile or is suspended.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from app.modules.xtream.domain import ALPHABET, MAX_ACTIVE_PER_USER, PASSWORD_LENGTH, USERNAME_LENGTH, XtreamPrincipal
from app.modules.xtream.models import XtreamCredential
from app.modules.xtream.services import CredentialService
from tests.support.client import PASSWORD, Api

BASE = "/api/v1/xtream/credentials"
CSRF = {"X-Requested-With": "XMLHttpRequest"}


def _authenticate(app: Flask, username: str, password: str) -> XtreamPrincipal | None:
    with app.app_context():
        return app.extensions["container"].resolve(CredentialService).authenticate(username, password)


def _profiles(api: Api, token: str) -> list[dict[str, Any]]:
    return list(api.get("/api/v1/profiles", token=token).data)


def _family(api: Api, name: str) -> str:
    token = api.user(name)
    assert api.post("/api/v1/billing/trial", token=token).status == 200  # family plan: room for more profiles
    return token


def _issue(api: Api, token: str, profile_id: int, label: str = "Living-room TV", **kw: Any) -> Any:
    return api.post(BASE, token=token, json={"label": label, "profile_id": profile_id}, **kw)


def test_issue_shows_the_password_once_and_stores_only_a_digest(app: Flask, api: Api) -> None:
    token = api.user("ada")
    profile = _profiles(api, token)[0]
    reply = _issue(api, token, profile["id"])
    assert reply.status == 201, reply.body
    issued = reply.data
    username, password = issued["credential"]["username"], issued["password"]
    assert len(username) == USERNAME_LENGTH and len(password) == PASSWORD_LENGTH
    assert set(username + password) <= set(ALPHABET)
    assert issued["server_url"] == "http://localhost:5173"
    assert issued["credential"]["profile_name"] == profile["name"]
    assert issued["credential"]["last_used_at"] is None

    listed = api.get(BASE, token=token).data
    assert [c["username"] for c in listed] == [username]
    assert "password" not in listed[0] and "secret_hash" not in listed[0]
    with app.app_context():
        from app.kernel.db import db

        stored = db.session.query(XtreamCredential).one()
        assert password not in stored.secret_hash and len(stored.secret_hash) == 64

    principal = _authenticate(app, username, password)
    assert principal is not None and principal.profile_id == profile["id"] and principal.is_kids is False
    assert api.get(BASE, token=token).data[0]["last_used_at"] is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda u, p: (u, p[:-1] + ("a" if p[-1] != "a" else "b")),  # wrong password
        lambda u, p: ("a" * USERNAME_LENGTH, p),  # unknown username
        lambda u, p: (u.upper(), p),  # not in the alphabet
        lambda u, p: (u, p + "a"),  # wrong length
        lambda u, p: (u, ""),
        lambda u, p: (u, PASSWORD),  # the account password is not an app credential
    ],
)
def test_authenticate_has_one_answer_for_every_failure(app: Flask, api: Api, mutate: Any) -> None:
    token = api.user("bea")
    issued = _issue(api, token, _profiles(api, token)[0]["id"]).data
    assert _authenticate(app, *mutate(issued["credential"]["username"], issued["password"])) is None


def test_revoke_stops_the_app_and_is_scoped_to_the_owner(app: Flask, api: Api) -> None:
    owner, other = api.user("cem"), api.user("deniz")
    issued = _issue(api, owner, _profiles(api, owner)[0]["id"]).data
    credential_id = issued["credential"]["id"]
    assert api.delete(f"{BASE}/{credential_id}", token=other).code == "XTREAM_CREDENTIAL_NOT_FOUND"
    assert api.delete(f"{BASE}/{credential_id}", token=owner).status == 204
    assert api.delete(f"{BASE}/{credential_id}", token=owner).code == "XTREAM_CREDENTIAL_NOT_FOUND"
    assert api.get(BASE, token=owner).data == []
    assert _authenticate(app, issued["credential"]["username"], issued["password"]) is None


def test_profile_must_be_the_owners_and_a_pin_must_have_been_entered(api: Api) -> None:
    owner, other = _family(api, "ece"), api.user("fikret")
    assert _issue(api, owner, _profiles(api, other)[0]["id"]).code == "XTREAM_PROFILE_NOT_FOUND"
    assert _issue(api, owner, 999_999).code == "XTREAM_PROFILE_NOT_FOUND"

    locked = api.post("/api/v1/profiles", token=owner, json={"name": "Private"}).data
    assert api.put(f"/api/v1/profiles/{locked['id']}/pin", token=owner, json={"pin": "1234"}).status == 200
    assert _issue(api, owner, locked["id"]).code == "XTREAM_PROFILE_LOCKED"  # PIN entered for another profile
    selected = api.post(f"/api/v1/profiles/{locked['id']}/select", token=owner, json={"pin": "1234"}).data
    header = {"X-Profile-Token": selected["profile_token"]}
    assert _issue(api, owner, locked["id"], headers=header).status == 201  # PIN entered in this session


def test_a_kids_profile_cannot_manage_credentials_but_can_be_watched_as(app: Flask, api: Api) -> None:
    owner = _family(api, "gul")
    kids = api.post("/api/v1/profiles", token=owner, json={"name": "Kids", "is_kids": True}).data
    issued = _issue(api, owner, kids["id"], label="Kids tablet").data  # from the adult (default) profile
    principal = _authenticate(app, issued["credential"]["username"], issued["password"])
    assert principal is not None and principal.is_kids is True  # the kids rating filter will apply

    selected = api.post(f"/api/v1/profiles/{kids['id']}/select", token=owner, json={}).data
    as_kids = {"X-Profile-Token": selected["profile_token"]}
    assert api.get(BASE, token=owner, headers=as_kids).code == "XTREAM_KIDS_PROFILE"
    assert _issue(api, owner, kids["id"], headers=as_kids).code == "XTREAM_KIDS_PROFILE"
    assert (
        api.delete(f"{BASE}/{issued['credential']['id']}", token=owner, headers=as_kids).code == "XTREAM_KIDS_PROFILE"
    )


def test_deleting_the_profile_revokes_its_credentials_only(app: Flask, api: Api) -> None:
    owner = _family(api, "hale")
    default_id = _profiles(api, owner)[0]["id"]
    second = api.post("/api/v1/profiles", token=owner, json={"name": "Guest"}).data
    keep = _issue(api, owner, default_id).data
    gone = _issue(api, owner, second["id"]).data
    assert api.delete(f"/api/v1/profiles/{second['id']}", token=owner).status == 204
    assert _authenticate(app, gone["credential"]["username"], gone["password"]) is None
    assert _authenticate(app, keep["credential"]["username"], keep["password"]) is not None
    assert [c["id"] for c in api.get(BASE, token=owner).data] == [keep["credential"]["id"]]


def test_a_new_account_password_revokes_every_credential(app: Flask, api: Api) -> None:
    token = api.user("ilke")
    issued = _issue(api, token, _profiles(api, token)[0]["id"]).data
    body = {"current_password": PASSWORD, "new_password": "Another-Strong-Pass-2026!"}
    reply = api.post("/api/v1/auth/change-password", json=body, token=token, headers=CSRF)
    assert reply.status == 200, reply.body
    assert _authenticate(app, issued["credential"]["username"], issued["password"]) is None
    assert api.get(BASE, token=reply.data["access_token"]).data == []


def test_a_suspended_account_is_refused_and_reactivation_restores_it(app: Flask, api: Api, admin: str) -> None:
    token = api.user("jale")
    issued = _issue(api, token, _profiles(api, token)[0]["id"]).data
    user_id = api.get("/api/v1/auth/me", token=token).data["id"]
    creds = (issued["credential"]["username"], issued["password"])
    assert api.post(f"/api/v1/admin/users/{user_id}/suspend", token=admin).status == 200
    assert _authenticate(app, *creds) is None
    assert api.post(f"/api/v1/admin/users/{user_id}/activate", token=admin).status == 200
    assert _authenticate(app, *creds) is not None  # suspension is a state, not a revocation


def test_active_credentials_are_capped_per_account(app: Flask, api: Api) -> None:
    token = api.user("kaan")
    profile_id = _profiles(api, token)[0]["id"]
    user_id = api.get("/api/v1/auth/me", token=token).data["id"]
    first = _issue(api, token, profile_id).data["credential"]
    with app.app_context():  # fill the account up directly: issuing is rate limited (5 at once)
        from app.kernel.db import db

        for n in range(MAX_ACTIVE_PER_USER - 1):
            db.session.add(
                XtreamCredential(
                    user_id=user_id,
                    profile_id=profile_id,
                    label=f"TV {n}",
                    username=f"seed{n:06d}",
                    secret_hash="0" * 64,
                )
            )
        db.session.commit()
    assert _issue(api, token, profile_id).code == "XTREAM_CREDENTIAL_LIMIT"
    assert api.delete(f"{BASE}/{first['id']}", token=token).status == 204  # revoked ones do not count
    assert _issue(api, token, profile_id).status == 201


def test_input_is_validated(api: Api) -> None:
    token = api.user("lale")
    profile_id = _profiles(api, token)[0]["id"]
    assert api.post(BASE, token=token, json={"label": "   ", "profile_id": profile_id}).status == 422
    assert api.post(BASE, token=token, json={"label": "x" * 41, "profile_id": profile_id}).status == 422
    assert api.post(BASE, token=token, json={"label": "TV", "profile_id": profile_id, "extra": 1}).status == 422
    assert api.get(BASE).code == "AUTH_REQUIRED"
