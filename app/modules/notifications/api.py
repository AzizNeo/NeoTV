"""PUBLIC surface of the notifications module. Other modules import only this file.

* ``EmailOutbox`` — capability ``notifications.email``: queue a templated mail
  inside the caller's unit of work (atomic with the caller's own changes).
* ``EmailTemplate`` — what a module contributes to ``notifications.templates``.
* ``EmailSender`` — what a transport contributes to ``notifications.email_senders``.
"""

from __future__ import annotations

import string
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from app.shared_kernel.locale import DEFAULT_LOCALE

POINT_TEMPLATES = "notifications.templates"
POINT_EMAIL_SENDERS = "notifications.email_senders"


@dataclass(frozen=True, slots=True)
class EmailTemplate:
    """``subject``/``text``/``html`` use ``{placeholder}`` fields (str.format).
    Values are HTML-escaped for ``html``; every placeholder is required.

    One template per (key, locale). The default-locale variant is mandatory; other languages are
    optional and must use exactly the same placeholders (checked when the catalogue is built).
    """

    key: str  # namespaced by the contributing module: "identity.password_reset"
    subject: str
    text: str
    html: str | None = None
    locale: str = DEFAULT_LOCALE

    @property
    def fields(self) -> frozenset[str]:
        parts = (self.subject, self.text, self.html or "")
        return frozenset(name for part in parts for _, name, _, _ in string.Formatter().parse(part) if name)


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    message_id: str
    to: str
    sender: str
    subject: str
    text: str
    html: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


class EmailSender(Protocol):
    name: str  # selected by settings.email_backend

    def send(self, message: RenderedEmail) -> None:
        """Deliver or raise. ``PermanentDeliveryError`` = do not retry."""


class EmailOutbox(Protocol):
    def queue(
        self,
        *,
        to: str,
        template: str,
        context: Mapping[str, str],
        dedupe_key: str | None = None,
        locale: str | None = None,
    ) -> str:
        """Validate and persist the message; delivery happens after commit. Returns the message id.

        ``locale``: the recipient's language; a template without that variant falls back to the default.
        """


__all__ = ["POINT_EMAIL_SENDERS", "POINT_TEMPLATES", "EmailOutbox", "EmailSender", "EmailTemplate", "RenderedEmail"]
