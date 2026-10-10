"""Account recovery end to end: verification on signup, forgot/reset, one-time links."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta

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
