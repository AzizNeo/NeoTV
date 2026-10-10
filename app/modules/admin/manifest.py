from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.extensions import ExtensionRegistry
from app.kernel.manifest import ExtensionSpec, ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.admin.api import POINT_ABUSE_RULES
from app.modules.admin.services import AbuseFlagNotFoundError, SessionNotFoundError
from app.modules.identity.api import IdentityAdmin
from app.modules.playback.api import SessionDirectory
from app.shared_kernel.events import UserLoggedIn


def _services(c: Any) -> None:
    from app.modules.admin.services import AbuseService, AdminService

    c.register(
        AdminService,
        lambda c: AdminService(
            identity=c.resolve(IdentityAdmin),
            sessions=c.resolve(SessionDirectory),
            capabilities=c.resolve(CapabilityIndex),
            clock=c.resolve(Clock),
        ),
    )
    c.register(
        AbuseService,
        lambda c: AbuseService(
            c.resolve(UnitOfWorkFactory),
            c.resolve(Clock),
            lambda: c.resolve(ExtensionRegistry).build(POINT_ABUSE_RULES, c),
        ),
    )


manifest = ModuleManifest(
    name="admin",
    version="2.0.0",
    description="Back office: dashboard via capabilities, user moderation, live sessions, abuse flags.",
    requires=frozenset({"identity.authentication", "identity.admin", "playback.sessions"}),
    optional_requires=frozenset({"catalog.read", "live.read", "devices.stats", "billing.reports", "drm.stats"}),
    models=("app.modules.admin.models",),
    services=_services,
    routes=(RouteSpec("app.modules.admin.http:blueprint", "/api/v1/admin"),),
    extension_points=(POINT_ABUSE_RULES,),
    extensions=(
        ExtensionSpec(POINT_ABUSE_RULES, "app.modules.admin.rules:build_many_ips_rule"),
        ExtensionSpec(POINT_ABUSE_RULES, "app.modules.admin.rules:build_many_devices_rule"),
    ),
    subscriptions=(
        SubscriptionSpec(
            UserLoggedIn.NAME, "admin.record_login_signal", "app.modules.admin.handlers:on_user_logged_in"
        ),
    ),
    task_modules=("app.modules.admin.tasks",),
    beat_schedule={"admin.evaluate-abuse": {"task": "admin.evaluate_abuse", "schedule": 900.0}},
    permissions=("admin:access",),
    error_map={
        AbuseFlagNotFoundError: (404, "ABUSE_FLAG_NOT_FOUND"),
        SessionNotFoundError: (404, "SESSION_NOT_FOUND"),
    },
)
