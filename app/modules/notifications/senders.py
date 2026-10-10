"""Built-in transports, contributed to ``notifications.email_senders``.

* ``smtp``    — production (STARTTLS / implicit TLS, timeouts, 5xx = permanent).
* ``console`` — development: logs the mail (links included) and writes an .eml.
* ``memory``  — tests: keeps messages in a list.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Any

from app.kernel.settings import Settings
from app.modules.notifications.api import RenderedEmail
from app.modules.notifications.domain import PermanentDeliveryError

_log = logging.getLogger("notifications.mail")
_URL = re.compile(r"https?://\S+")


def to_mime(message: RenderedEmail) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = message.sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Date"] = formatdate(localtime=False)
    mime["Message-ID"] = make_msgid(idstring=message.message_id.replace("-", ""))
    for name, value in message.headers.items():
        mime[name] = value
    mime.set_content(message.text)
    if message.html:
        mime.add_alternative(message.html, subtype="html")
    return mime


class SmtpEmailSender:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def send(self, message: RenderedEmail) -> None:
        s = self._s
        if not s.smtp_host:
            raise PermanentDeliveryError("SMTP_HOST is not configured")
        context = ssl.create_default_context()
        smtp_cls = smtplib.SMTP_SSL if s.smtp_security == "ssl" else smtplib.SMTP
        kwargs: dict[str, Any] = {"timeout": s.smtp_timeout_s}
        if s.smtp_security == "ssl":
            kwargs["context"] = context
        try:
            with smtp_cls(s.smtp_host, s.smtp_port, **kwargs) as client:
                if s.smtp_security == "starttls":
                    client.starttls(context=context)
                if s.smtp_username and s.smtp_password:
                    client.login(s.smtp_username, s.smtp_password.get_secret_value())
                client.send_message(to_mime(message))
        except smtplib.SMTPResponseException as exc:
            if 500 <= exc.smtp_code < 600:  # permanent per RFC 5321
                raise PermanentDeliveryError(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}") from exc
            raise  # 4xx: transient → outbox retry with backoff
        except smtplib.SMTPRecipientsRefused as exc:
            raise PermanentDeliveryError(f"recipient refused: {list(exc.recipients)}") from exc


class ConsoleEmailSender:
    name = "console"

    def __init__(self, settings: Settings) -> None:
        self._dir = Path(settings.mail_dir)

    def send(self, message: RenderedEmail) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{message.message_id}.eml"
        path.write_bytes(bytes(to_mime(message)))
        links = " ".join(_URL.findall(message.text))
        _log.info("mail.console to=%s subject=%r file=%s links=%s", message.to, message.subject, path, links)


class MemoryEmailSender:
    name = "memory"

    def __init__(self) -> None:
        self.outbox: list[RenderedEmail] = []

    def send(self, message: RenderedEmail) -> None:
        self.outbox.append(message)


_MEMORY = MemoryEmailSender()  # one per process: tests read it via memory_sender()


def memory_sender() -> MemoryEmailSender:
    return _MEMORY


def smtp_factory(c: Any) -> SmtpEmailSender:
    return SmtpEmailSender(c.resolve(Settings))


def console_factory(c: Any) -> ConsoleEmailSender:
    return ConsoleEmailSender(c.resolve(Settings))


def memory_factory(_c: Any) -> MemoryEmailSender:
    return _MEMORY
