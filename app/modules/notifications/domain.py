from __future__ import annotations

from enum import StrEnum


class NotificationError(Exception):
    def __init__(self, message: str = "", *, details: object = None) -> None:
        super().__init__(message)
        self.details = details


class UnknownTemplateError(NotificationError):
    """No module contributed a template with this key."""


class TemplateContextError(NotificationError):
    """Context is missing placeholders the template needs (or has unknown ones)."""


class DuplicateTemplateError(NotificationError):
    """Two contributions declare the same template key."""


class TemplateLocaleError(NotificationError):
    """A translated template is unusable: unknown language, no default variant, or placeholders differ."""


class InvalidRecipientError(NotificationError):
    pass


class EmailSenderNotFoundError(NotificationError):
    """settings.email_backend names a transport nobody contributed."""


class PermanentDeliveryError(NotificationError):
    """The transport rejected the message for good (e.g. SMTP 5xx) — no retry."""


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
