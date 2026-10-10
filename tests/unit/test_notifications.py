"""notifications: templates, transports, queue → outbox → delivery."""

from __future__ import annotations

import smtplib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.notifications.api import EmailTemplate, RenderedEmail
from app.modules.notifications.domain import (
    DuplicateTemplateError,
    EmailSenderNotFoundError,
    InvalidRecipientError,
    PermanentDeliveryError,
    TemplateContextError,
    UnknownTemplateError,
)
from app.modules.notifications.senders import ConsoleEmailSender, MemoryEmailSender, SmtpEmailSender
from app.modules.notifications.services import TemplateCatalog, normalise_address, select_sender
from tests.support.factory import make_settings

GREETING = EmailTemplate(
    key="test.greeting",
    subject="Merhaba {name}",
    text="Selam {name}: {link}",
    html="<p>{name}</p><a href='{link}'>x</a>",
)


def _catalog(*groups: list[EmailTemplate]) -> TemplateCatalog:
    return TemplateCatalog(lambda: list(groups))


def test_template_fields_and_html_escaping() -> None:
    assert GREETING.fields == {"name", "link"}
    subject, text, html = _catalog([GREETING]).render("test.greeting", {"name": "<b>Ali</b>", "link": "https://x/#t=1"})
    assert subject == "Merhaba <b>Ali</b>"  # plain-text parts are not escaped
    assert "&lt;b&gt;Ali&lt;/b&gt;" in (html or "") and "<b>" not in (html or "")
    assert text == "Selam <b>Ali</b>: https://x/#t=1"


def test_catalog_contract_errors_are_named() -> None:
    with pytest.raises(DuplicateTemplateError):
        _catalog([GREETING], [GREETING]).keys()
    with pytest.raises(UnknownTemplateError):
        _catalog([GREETING]).get("test.nope")
    with pytest.raises(TemplateContextError) as info:
        _catalog([GREETING]).check_context("test.greeting", {"name": "a", "extra": "b"})
    assert info.value.details == {"missing": ["link"], "unknown": ["extra"]}


def test_recipient_normalisation() -> None:
    assert normalise_address("Ali@Example.COM") == "Ali@example.com"
    with pytest.raises(InvalidRecipientError):
        normalise_address("not-an-address")


def test_unknown_backend_fails_with_available_list() -> None:
    with pytest.raises(EmailSenderNotFoundError) as info:
        select_sender([MemoryEmailSender()], "sendgrid")
    assert info.value.details == {"available": ["memory"]}


def _mail() -> RenderedEmail:
    return RenderedEmail(
        message_id="m-1", to="a@example.com", sender="T <n@example.com>", subject="S", text="https://x/y"
    )


def test_console_sender_writes_eml(tmp_path: Path) -> None:
    ConsoleEmailSender(make_settings(mail_dir=tmp_path)).send(_mail())
    eml = (tmp_path / "m-1.eml").read_text()
    assert "Subject: S" in eml and "https://x/y" in eml


class _FakeSmtp:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.sent: list[Any] = []

    def __call__(self, *_a: Any, **_k: Any) -> _FakeSmtp:
        return self

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self, **_k: Any) -> None:
        return None

    def login(self, *_a: Any) -> None:
        return None

    def send_message(self, message: Any) -> None:
        if self.error:
            raise self.error
        self.sent.append(message)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, None),
        (smtplib.SMTPResponseException(550, b"no such user"), PermanentDeliveryError),
        (smtplib.SMTPResponseException(451, b"try later"), smtplib.SMTPResponseException),
    ],
)
def test_smtp_classifies_permanent_vs_transient(
    monkeypatch: pytest.MonkeyPatch, error: Exception | None, expected: type[Exception] | None
) -> None:
    fake = _FakeSmtp(error)
    monkeypatch.setattr(smtplib, "SMTP", fake)
    sender = SmtpEmailSender(make_settings(email_backend="smtp", smtp_host="smtp.example.com"))
    if expected is None:
        sender.send(_mail())
        assert fake.sent[0]["To"] == "a@example.com"
    else:
        with pytest.raises(expected):
            sender.send(_mail())


def test_settings_guard_e_mail_configuration() -> None:
    with pytest.raises(ValidationError, match="SMTP_HOST is required"):
        make_settings(email_backend="smtp")
    with pytest.raises(ValidationError, match="EMAIL_BACKEND=console is not allowed in prod"):
        make_settings(env="prod", email_backend="console")


# ── through the real app: queue (in a UoW) → outbox → delivery → redaction ──


def _app_with_template(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.kernel.extensions import ExtensionRegistry
    from tests.support.factory import make_app

    original = ExtensionRegistry.build

    def build(self: ExtensionRegistry, point: str, container: Any) -> list[Any]:
        built = original(self, point, container)
        return [*built, [GREETING]] if point == "notifications.templates" else built

    monkeypatch.setattr(ExtensionRegistry, "build", build)
    return make_app()


def test_queue_deliver_and_redact(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.kernel.container import resolve
    from app.kernel.db import db
    from app.kernel.outbox.trigger import dispatch_if_pending
    from app.modules.notifications.api import EmailOutbox
    from app.modules.notifications.models import EmailMessage
    from app.modules.notifications.senders import memory_sender

    app = _app_with_template(monkeypatch)
    outbox = memory_sender().outbox
    outbox.clear()
    with app.app_context():
        mailer = resolve(EmailOutbox)
        message_id = mailer.queue(to="ali@example.com", template="test.greeting", context={"name": "Ali", "link": "L"})
        again = mailer.queue(
            to="ali@example.com", template="test.greeting", context={"name": "Ali", "link": "L"}, dedupe_key="k1"
        )
        assert again != message_id
        assert (
            mailer.queue(
                to="ali@example.com", template="test.greeting", context={"name": "X", "link": "Y"}, dedupe_key="k1"
            )
            == again
        )  # idempotent by dedupe key
        dispatch_if_pending(op="test")
        stored = db.session.get(EmailMessage, message_id)
        assert stored is not None and stored.status == "sent" and stored.context_json is None and stored.sent_at
    assert [m.subject for m in outbox] == ["Merhaba Ali", "Merhaba Ali"]
