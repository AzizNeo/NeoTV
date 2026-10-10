from __future__ import annotations

from typing import Any

from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.security.device_keys import DeviceKeys
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.devices.api import DeviceStats
from app.modules.devices.services import DeviceNotFoundError, DeviceService
from app.shared_kernel.events import UserLoggedIn


def _services(c: Any) -> None:
    c.register(
        DeviceService, lambda c: DeviceService(c.resolve(UnitOfWorkFactory), c.resolve(DeviceKeys), c.resolve(Clock))
    )
    c.register(DeviceStats, lambda c: c.resolve(DeviceService))


manifest = ModuleManifest(
    name="devices",
    version="2.0.0",
    description="Device inventory per account; revocation ends sessions and streams via events.",
    provides={"devices.stats": DeviceStats},
    requires=frozenset({"identity.authentication"}),
    models=("app.modules.devices.models",),
    services=_services,
    routes=(RouteSpec("app.modules.devices.http:blueprint", "/api/v1/devices"),),
    subscriptions=(
        SubscriptionSpec(UserLoggedIn.NAME, "devices.track_login", "app.modules.devices.handlers:on_user_logged_in"),
    ),
    error_map={DeviceNotFoundError: (404, "DEVICE_NOT_FOUND")},
)
