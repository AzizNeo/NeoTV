from __future__ import annotations

from typing import Any

from app.kernel.extensions import ExtensionRegistry
from app.kernel.manifest import ExtensionSpec, ModuleManifest, SubscriptionSpec
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.notifications.api import POINT_EMAIL_SENDERS, POINT_TEMPLATES, EmailOutbox
from app.modules.notifications.domain import (
    InvalidRecipientError,
    TemplateContextError,
    UnknownTemplateError,
)
from app.shared_kernel.events import EmailQueued


def _services(c: Any) -> None:
    from app.modules.notifications.services import (
        EmailDeliveryService,
        EmailOutboxService,
        TemplateCatalog,
        select_sender,
    )

    c.register(
        TemplateCatalog, lambda c: TemplateCatalog(lambda: c.resolve(ExtensionRegistry).build(POINT_TEMPLATES, c))
    )
    c.register(
        EmailOutboxService,
        lambda c: EmailOutboxService(c.resolve(UnitOfWorkFactory), c.resolve(TemplateCatalog), c.resolve(Clock)),
    )
    c.register(EmailOutbox, lambda c: c.resolve(EmailOutboxService))

    def _delivery(c: Any) -> EmailDeliveryService:
        settings = c.resolve(Settings)
        chosen: list[Any] = []

        def sender() -> Any:
            if not chosen:
                senders = c.resolve(ExtensionRegistry).build(POINT_EMAIL_SENDERS, c)
                chosen.append(select_sender(senders, settings.email_backend))
            return chosen[0]

        return EmailDeliveryService(c.resolve(TemplateCatalog), sender, settings.email_from, c.resolve(Clock))

    c.register(EmailDeliveryService, _delivery)


manifest = ModuleManifest(
    name="notifications",
    version="1.0.0",
    description="Transactional e-mail: module-contributed templates, pluggable transports, outbox delivery.",
    provides={"notifications.email": EmailOutbox},
    models=("app.modules.notifications.models",),
    services=_services,
    subscriptions=(
        SubscriptionSpec(
            EmailQueued.NAME, "notifications.deliver_email", "app.modules.notifications.handlers:on_email_queued"
        ),
    ),
    task_modules=("app.modules.notifications.tasks",),
    beat_schedule={
        "notifications.redact-stale": {"task": "notifications.redact_stale", "schedule": 3600.0},
    },
    extension_points=(POINT_TEMPLATES, POINT_EMAIL_SENDERS),
    extensions=(
        ExtensionSpec(POINT_EMAIL_SENDERS, "app.modules.notifications.senders:smtp_factory"),
        ExtensionSpec(POINT_EMAIL_SENDERS, "app.modules.notifications.senders:console_factory"),
        ExtensionSpec(POINT_EMAIL_SENDERS, "app.modules.notifications.senders:memory_factory"),
    ),
    error_map={
        UnknownTemplateError: (500, "EMAIL_TEMPLATE_UNKNOWN"),
        TemplateContextError: (500, "EMAIL_TEMPLATE_CONTEXT"),
        InvalidRecipientError: (422, "EMAIL_RECIPIENT_INVALID"),
    },
    post_boot="app.modules.notifications.post_boot:validate",
)
