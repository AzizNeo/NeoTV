from __future__ import annotations

from typing import Any

from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules._template.api import TemplateReader
from app.modules._template.domain import TemplateItemNotFoundError
from app.shared_kernel.events import UserStatusChanged


def _services(c: Any) -> None:
    from app.modules._template.services import TemplateService

    c.register(TemplateService, lambda c: TemplateService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(TemplateReader, lambda c: c.resolve(TemplateService))


manifest = ModuleManifest(
    name="_template",
    version="0.1.0",
    description="Skeleton module — replace this description.",
    provides={"_template.read": TemplateReader},
    requires=frozenset({"identity.authentication"}),
    models=("app.modules._template.models",),
    services=_services,
    routes=(RouteSpec("app.modules._template.http:blueprint", "/api/v1/_template"),),
    subscriptions=(
        SubscriptionSpec(
            UserStatusChanged.NAME, "_template.purge_suspended", "app.modules._template.handlers:on_user_status_changed"
        ),
    ),
    task_modules=("app.modules._template.tasks",),
    error_map={TemplateItemNotFoundError: (404, "_TEMPLATE_ITEM_NOT_FOUND")},
)
