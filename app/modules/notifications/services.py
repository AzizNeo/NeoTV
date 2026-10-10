"""Queueing (in the caller's unit of work) and delivery (outbox consumer)."""

from __future__ import annotations

import html
import json
import logging
from collections.abc import Callable, Mapping
from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select, update

from app.kernel.time import Clock
from app.kernel.uow import UnitOfWork, UnitOfWorkFactory
from app.modules.notifications.api import EmailSender, EmailTemplate, RenderedEmail
from app.modules.notifications.domain import (
    DuplicateTemplateError,
    EmailSenderNotFoundError,
    InvalidRecipientError,
    MessageStatus,
    PermanentDeliveryError,
    TemplateContextError,
    UnknownTemplateError,
)
from app.modules.notifications.models import EmailMessage
from app.shared_kernel.events import EmailQueued

_log = logging.getLogger("notifications.delivery")
MAX_ERROR_LEN = 500


class TemplateCatalog:
    """Templates contributed by modules. Built lazily (after every module registered)."""

    def __init__(self, load: Callable[[], list[list[EmailTemplate]]]) -> None:
        self._load = load
        self._templates: dict[str, EmailTemplate] | None = None

    def _all(self) -> dict[str, EmailTemplate]:
        if self._templates is None:
            catalog: dict[str, EmailTemplate] = {}
            for contribution in self._load():
                for template in contribution:
                    if template.key in catalog:
                        raise DuplicateTemplateError(f"template '{template.key}' contributed twice")
                    catalog[template.key] = template
            self._templates = catalog
        return self._templates

    def keys(self) -> list[str]:
        return sorted(self._all())

    def get(self, key: str) -> EmailTemplate:
        template = self._all().get(key)
        if template is None:
            raise UnknownTemplateError(f"no module contributed e-mail template '{key}'", details={"template": key})
        return template

    def check_context(self, key: str, context: Mapping[str, str]) -> EmailTemplate:
        template = self.get(key)
        missing = sorted(template.fields - context.keys())
        unknown = sorted(context.keys() - template.fields)
        if missing or unknown:
            raise TemplateContextError(
                f"context does not match template '{key}'", details={"missing": missing, "unknown": unknown}
            )
        return template

    def render(self, key: str, context: Mapping[str, str]) -> tuple[str, str, str | None]:
        template = self.check_context(key, context)
        escaped = {name: html.escape(str(value)) for name, value in context.items()}
        subject = template.subject.format_map(context).replace("\n", " ").strip()
        return subject, template.text.format_map(context), template.html.format_map(escaped) if template.html else None


def normalise_address(address: str) -> str:
    try:
        return validate_email(address, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise InvalidRecipientError(str(exc)) from exc


class EmailOutboxService:
    """Capability ``notifications.email``."""

    def __init__(self, uow: UnitOfWorkFactory, catalog: TemplateCatalog, clock: Clock) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock

    def queue(self, *, to: str, template: str, context: Mapping[str, str], dedupe_key: str | None = None) -> str:
        self._catalog.check_context(template, context)  # fail in the caller's request, not in a worker
        address = normalise_address(to)
        with self._uow() as uow:  # joins the caller's transaction (re-entrant UoW)
            if dedupe_key:
                existing = uow.session.execute(
                    select(EmailMessage.id).where(EmailMessage.dedupe_key == dedupe_key)
                ).scalar_one_or_none()
                if existing:
                    return str(existing)
            message = EmailMessage(
                to_address=address,
                template=template,
                context_json=json.dumps(dict(context), ensure_ascii=False),
                dedupe_key=dedupe_key,
                status=MessageStatus.QUEUED,
                attempts=0,
                created_at=self._clock.now(),
            )
            uow.session.add(message)
            uow.flush()
            uow.outbox.add(EmailQueued(message_id=message.id, template=template))
            return str(message.id)


class EmailDeliveryService:
    def __init__(self, catalog: TemplateCatalog, sender: Callable[[], EmailSender], sender_address: str, clock: Clock):
        self._catalog = catalog
        self._sender = sender
        self._from = sender_address
        self._clock = clock

    def transport_name(self) -> str:
        """Resolves (and thereby validates) the configured transport."""
        return self._sender().name

    def deliver(self, uow: UnitOfWork, message_id: str) -> str:
        message = uow.session.get(EmailMessage, message_id)
        if message is None or message.status != MessageStatus.QUEUED or message.context_json is None:
            return "skipped"
        message.attempts += 1
        subject, text, html_body = self._catalog.render(message.template, json.loads(message.context_json))
        rendered = RenderedEmail(
            message_id=message.id, to=message.to_address, sender=self._from, subject=subject, text=text, html=html_body
        )
        try:
            self._sender().send(rendered)
        except PermanentDeliveryError as exc:
            self._finish(message, MessageStatus.FAILED, error=str(exc))
            _log.error("mail.failed id=%s template=%s err=%s", message.id, message.template, exc)
            return "failed"
        except Exception as exc:
            # Transient (network, 4xx): the outbox rolls back, retries with backoff and
            # dead-letters after its limit; redact_stale clears the context of any
            # message that never made it.
            _log.warning("mail.retry id=%s attempt=%s err=%r", message.id, message.attempts, exc)
            raise
        self._finish(message, MessageStatus.SENT)
        return "sent"

    def _finish(self, message: EmailMessage, status: MessageStatus, *, error: str | None = None) -> None:
        message.status = status
        message.context_json = None  # one-time links must not outlive delivery
        message.last_error = error[:MAX_ERROR_LEN] if error else None
        if status is MessageStatus.SENT:
            message.sent_at = self._clock.now()

    @staticmethod
    def redact_stale(uow: UnitOfWork, *, older_than: timedelta, now_fn: Callable[[], object]) -> int:
        cutoff = now_fn() - older_than  # type: ignore[operator]
        result = uow.session.execute(
            update(EmailMessage)
            .where(EmailMessage.context_json.is_not(None), EmailMessage.created_at < cutoff)
            .values(context_json=None)
        )
        return int(result.rowcount or 0)


def select_sender(senders: list[EmailSender], backend: str) -> EmailSender:
    by_name = {sender.name: sender for sender in senders}
    try:
        return by_name[backend]
    except KeyError:
        raise EmailSenderNotFoundError(
            f"EMAIL_BACKEND={backend!r} but no transport with that name is contributed",
            details={"available": sorted(by_name)},
        ) from None
