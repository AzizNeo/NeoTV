"""Account recovery end to end: verification on signup, forgot/reset, one-time links."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from flask import Flask

from app.modules.notifications.api import RenderedEmail
from app.modules.notifications.senders import memory_sender
from tests.support.client import PASSWORD, Api
from tests.support.factory import make_app

CSRF = {"X-Requested-With": "XMLHttpRequest"}
NEW_PASSWORD = "Brand-New-Secret9"
TOKEN = re.compile(r"#token=([A-Za-z0-9_-]+)")


@pytest.fixture(autouse=True)
def mailbox() -> Iterator[list[RenderedEmail]]:
    outbox = memory_sender().outbox
    outbox.clear()
    yield outbox
    outbox.clear()


def _token(mail: RenderedEmail) -> str:
    match = TOKEN.search(mail.text)
    assert match, mail.text
    return match.group(1)


def _mails_to(mailbox: list[RenderedEmail], to: str, subject_part: str) -> list[RenderedEmail]:
    return [m for m in mailbox if m.to == to and subject_part in m.subject]


def _backdate(app: Flask, purpose: str, **delta: timedelta) -> None:
    from app.kernel.db import db
    from app.modules.identity.models import ActionToken

    with app.app_context():
        for token in db.session.query(ActionToken).filter_by(purpose=purpose):
            for column, shift in delta.items():
                setattr(token, column, getattr(token, column) - shift)
        db.session.commit()


def test_signup_sends_verification_and_link_verifies_once(api: Api, mailbox: list[RenderedEmail]) -> None:
    assert api.register("vera", email="Vera@Example.com").status == 201
    [mail] = _mails_to(mailbox, "vera@example.com", "doğrulayın")
    assert "/verify-email#token=" in mail.text and mail.html and "<a href=" in mail.html
    token = api.login("vera").data["access_token"]
    assert api.get("/api/v1/auth/me", token=token).data["email_verified"] is False

    assert api.post("/api/v1/auth/email/verify", json={"token": _token(mail)}).status == 200
    assert api.get("/api/v1/auth/me", token=token).data["email_verified"] is True
    assert api.post("/api/v1/auth/email/verify", json={"token": _token(mail)}).code == "ACTION_TOKEN_INVALID"
    assert api.post("/api/v1/auth/email/verification", token=token).code == "EMAIL_ALREADY_VERIFIED"


def test_resend_verification_rules(api: Api, mailbox: list[RenderedEmail]) -> None:
    no_mail = api.user("nomail")
    assert api.post("/api/v1/auth/email/verification", token=no_mail).code == "EMAIL_MISSING"
    api.register("resend", email="resend@example.com")
    token = api.login("resend").data["access_token"]
    assert api.post("/api/v1/auth/email/verification", token=token).status == 202  # within cooldown → no 2nd mail
    assert len(_mails_to(mailbox, "resend@example.com", "doğrulayın")) == 1


def test_forgot_password_does_not_reveal_accounts(api: Api, mailbox: list[RenderedEmail]) -> None:
    unknown = api.post("/api/v1/auth/password/forgot", json={"email": "ghost@example.com"})
    api.register("rita", email="rita@example.com")
    known = api.post("/api/v1/auth/password/forgot", json={"email": "RITA@example.com"})
    assert unknown.status == known.status == 202 and unknown.body["message"] == known.body["message"]
    assert _mails_to(mailbox, "ghost@example.com", "") == []
    assert len(_mails_to(mailbox, "rita@example.com", "sıfırlama")) == 1
    api.post("/api/v1/auth/password/forgot", json={"email": "rita@example.com"})  # cooldown: still one mail
    assert len(_mails_to(mailbox, "rita@example.com", "sıfırlama")) == 1


def test_reset_password_revokes_everything_and_is_single_use(api: Api, mailbox: list[RenderedEmail]) -> None:
    api.register("rob", email="rob@example.com")
    old_access = api.login("rob").data["access_token"]
    api.post("/api/v1/auth/password/forgot", json={"email": "rob@example.com"})
    raw = _token(_mails_to(mailbox, "rob@example.com", "sıfırlama")[0])

    weak = api.post("/api/v1/auth/password/reset", json={"token": raw, "new_password": "short"})
    assert weak.code == "WEAK_PASSWORD"  # validation failure does not burn the link
    done = api.post("/api/v1/auth/password/reset", json={"token": raw, "new_password": NEW_PASSWORD})
    assert done.status == 200

    assert api.get("/api/v1/auth/me", token=old_access).status == 401  # token_version bumped
    assert api.post("/api/v1/auth/refresh", headers=CSRF).status == 401  # refresh family revoked
    assert api.login("rob", PASSWORD).code == "INVALID_CREDENTIALS"
    fresh = api.login("rob", NEW_PASSWORD).data["access_token"]
    assert api.get("/api/v1/auth/me", token=fresh).data["email_verified"] is True  # link proved the inbox
    assert api.post("/api/v1/auth/password/reset", json={"token": raw, "new_password": NEW_PASSWORD}).code == (
        "ACTION_TOKEN_INVALID"
    )
    assert len(_mails_to(mailbox, "rob@example.com", "değiştirildi")) == 1  # owner is notified


def test_expired_and_superseded_links_are_rejected(app: Flask, api: Api, mailbox: list[RenderedEmail]) -> None:
    api.register("eve", email="eve@example.com")
    api.post("/api/v1/auth/password/forgot", json={"email": "eve@example.com"})
    first = _token(_mails_to(mailbox, "eve@example.com", "sıfırlama")[0])
    _backdate(app, "reset_password", created_at=timedelta(minutes=5))  # past the cooldown
    api.post("/api/v1/auth/password/forgot", json={"email": "eve@example.com"})
    second = _token(_mails_to(mailbox, "eve@example.com", "sıfırlama")[1])
    body = {"new_password": NEW_PASSWORD}
    assert api.post("/api/v1/auth/password/reset", json={"token": first, **body}).code == "ACTION_TOKEN_INVALID"

    _backdate(app, "reset_password", expires_at=timedelta(hours=1))
    assert api.post("/api/v1/auth/password/reset", json={"token": second, **body}).code == "ACTION_TOKEN_INVALID"
    assert api.post("/api/v1/auth/password/reset", json={"token": "x" * 43, **body}).code == "ACTION_TOKEN_INVALID"


def test_without_notifications_module_recovery_fails_loudly_signup_still_works() -> None:
    app = make_app(disabled_modules="notifications")
    api = Api(app)
    assert api.register("solo", email="solo@example.com").status == 201  # verification mail silently skipped
    reply = api.post("/api/v1/auth/password/forgot", json={"email": "solo@example.com"})
    assert (reply.status, reply.code) == (503, "EMAIL_DELIVERY_UNAVAILABLE")


def test_self_service_password_change_notifies_the_owner(api: Api, mailbox: list[RenderedEmail]) -> None:
    api.register("cleo", email="cleo@example.com")
    token = api.login("cleo").data["access_token"]
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert api.post("/api/v1/auth/change-password", json=body, token=token, headers=CSRF).status == 200
    assert len(_mails_to(mailbox, "cleo@example.com", "değiştirildi")) == 1
    wrong = api.post(
        "/api/v1/auth/change-password",
        json=body,
        token=api.login("cleo", NEW_PASSWORD).data["access_token"],
        headers=CSRF,
    )
    assert wrong.code == "INVALID_CREDENTIALS"  # failed attempts publish nothing
    assert len(_mails_to(mailbox, "cleo@example.com", "değiştirildi")) == 1


# ── e-mail change ────────────────────────────────────────────────────────────
def _change(api: Api, token: str, new_email: str, password: str = PASSWORD) -> Any:
    return api.post("/api/v1/auth/email/change", json={"new_email": new_email, "password": password}, token=token)


def _confirm_change(api: Api, mailbox: list[RenderedEmail], new_email: str) -> None:
    raw = _token(_mails_to(mailbox, new_email, "onaylayın")[-1])
    assert api.post("/api/v1/auth/email/change/confirm", json={"token": raw}).status == 200


def test_email_change_is_confirmed_from_the_new_inbox(api: Api, mailbox: list[RenderedEmail]) -> None:
    api.register("eve", email="eve@example.com")
    api.register("taken", email="taken@example.com")
    token = api.login("eve").data["access_token"]
    api.post("/api/v1/auth/password/forgot", json={"email": "eve@example.com"})
    stale_reset = _token(_mails_to(mailbox, "eve@example.com", "sıfırlama")[0])

    assert _change(api, token, "new@example.com", password="wrong").code == "INVALID_CREDENTIALS"
    assert _change(api, token, "EVE@example.com").code == "EMAIL_UNCHANGED"
    assert _change(api, token, "taken@example.com").code == "EMAIL_TAKEN"
    assert _change(api, token, "New@Example.com").status == 202
    assert api.get("/api/v1/auth/me", token=token).data["email"] == "eve@example.com"  # nothing changed yet
    [warning] = _mails_to(mailbox, "eve@example.com", "istendi")
    assert "n***@example.com" in warning.text and "new@example.com" not in warning.text

    _confirm_change(api, mailbox, "new@example.com")
    me = api.get("/api/v1/auth/me", token=token).data
    assert me["email"] == "new@example.com" and me["email_verified"] is True  # sessions survive a normal change
    reset = api.post("/api/v1/auth/password/reset", json={"token": stale_reset, "new_password": NEW_PASSWORD})
    assert reset.code == "ACTION_TOKEN_INVALID"  # links sent to the old inbox died with the change
    [notice] = _mails_to(mailbox, "eve@example.com", "değiştirildi")
    assert "/revert-email-change#token=" in notice.text


def test_old_inbox_can_undo_a_takeover_and_wins_a_chain(app: Flask, api: Api, mailbox: list[RenderedEmail]) -> None:
    api.register("owner", email="owner@example.com")
    attacker = api.login("owner").data["access_token"]
    assert _change(api, attacker, "a@evil.example.org").status == 202
    _confirm_change(api, mailbox, "a@evil.example.org")
    _backdate(app, "change_email", created_at=timedelta(minutes=5))  # past the burst guard
    assert _change(api, attacker, "b@evil.example.org").status == 202
    _confirm_change(api, mailbox, "b@evil.example.org")
    owner_undo = _token(_mails_to(mailbox, "owner@example.com", "değiştirildi")[0])
    attacker_undo = _token(_mails_to(mailbox, "a@evil.example.org", "değiştirildi")[0])

    revert = api.post("/api/v1/auth/email/change/revert", json={"token": owner_undo})
    assert revert.status == 200  # the second change did not cancel the owner's undo link
    assert api.get("/api/v1/auth/me", token=attacker).status == 401  # every session ended
    assert api.post("/api/v1/auth/refresh", headers=CSRF).status == 401
    assert len(_mails_to(mailbox, "owner@example.com", "sıfırlama")) == 1  # reset link handed to the owner
    assert api.post("/api/v1/auth/email/change/revert", json={"token": attacker_undo}).code == "ACTION_TOKEN_INVALID"
    me = api.get("/api/v1/auth/me", token=api.login("owner").data["access_token"]).data
    assert me["email"] == "owner@example.com" and me["email_verified"] is True


# ── new-device alert ─────────────────────────────────────────────────────────
PHONE = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1"
}


def test_sign_in_from_a_new_device_alerts_the_owner_once(api: Api, mailbox: list[RenderedEmail]) -> None:
    api.register("nina", email="nina@example.com")
    api.login("nina")
    api.login("nina")  # first and only device so far (signup) → not news
    assert _mails_to(mailbox, "nina@example.com", "yeni bir cihaz") == []

    assert api.login("nina", headers=PHONE).status == 200
    [alert] = _mails_to(mailbox, "nina@example.com", "yeni bir cihaz")
    assert "iPhone" in alert.text or "iOS" in alert.text, alert.text
    assert "IP adresi:" in alert.text and "Cihazlar" in alert.text

    api.login("nina", headers=PHONE)  # known device now
    assert len(_mails_to(mailbox, "nina@example.com", "yeni bir cihaz")) == 1


# ── language ───────────────────────────────────────────────────────────────


def test_mails_speak_the_account_language(api: Api, mailbox: list[RenderedEmail]) -> None:
    english = {"Accept-Language": "en-GB,en;q=0.9,tr;q=0.5"}
    signup = api.post(
        "/api/v1/auth/register",
        json={"username": "emma", "password": PASSWORD, "email": "emma@example.com"},
        headers=english,
    )
    assert signup.status == 201
    [mail] = _mails_to(mailbox, "emma@example.com", "verify your e-mail")  # signed up in English
    assert "/verify-email#token=" in mail.text and "Hi emma" in mail.text

    token = api.login("emma").data["access_token"]
    assert api.get("/api/v1/auth/me", token=token).data["locale"] == "en"
    # The account language is one choice for every device: switching to Turkish switches the mails.
    assert api.put("/api/v1/auth/me/locale", json={"locale": "tr"}, token=token).data["locale"] == "tr"
    api.post("/api/v1/auth/password/forgot", json={"email": "emma@example.com"})
    assert len(_mails_to(mailbox, "emma@example.com", "şifre sıfırlama")) == 1
    assert api.put("/api/v1/auth/me/locale", json={"locale": "de"}, token=token).code == "VALIDATION_FAILED"


def test_older_accounts_adopt_the_browser_language_once(api: Api) -> None:
    api.register("oldtimer")  # no Accept-Language → no language recorded
    token = api.login("oldtimer").data["access_token"]
    assert api.get("/api/v1/auth/me", token=token).data["locale"] is None
    api.login("oldtimer", headers={"Accept-Language": "en-US"})
    assert api.get("/api/v1/auth/me", token=token).data["locale"] == "en"
    api.login("oldtimer", headers={"Accept-Language": "tr"})  # a later browser never overrides a choice
    assert api.get("/api/v1/auth/me", token=token).data["locale"] == "en"
