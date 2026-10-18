from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.xtream.domain import (
    CredentialLimitReachedError,
    CredentialNotFoundError,
    KidsProfileManagementError,
    ProfileLockedError,
    ProfileNotOwnedError,
)
from app.modules.xtream.services import CredentialService
from app.shared_kernel.events import PasswordChanged, ProfileDeleted


def _services(c: Any) -> None:
    def credentials(c: Any) -> CredentialService:
        settings = c.resolve(Settings)
        capabilities = c.resolve(CapabilityIndex)
        return CredentialService(
            c.resolve(UnitOfWorkFactory),
            c.resolve(Clock),
            key=settings.derive_key("xtream/credentials"),
            users=capabilities.required("identity.users"),
            profiles=capabilities.required("profile.directory"),
            server_url=settings.frontend_base_url,
        )

    c.register(CredentialService, credentials)


manifest = ModuleManifest(
    name="xtream",
    version="0.1.0",
    description="Xtream-compatible player API for TV apps: per-device app credentials bound to a profile.",
    requires=frozenset({"identity.authentication", "identity.users", "profile.context", "profile.directory"}),
    models=("app.modules.xtream.models",),
    services=_services,
    routes=(RouteSpec("app.modules.xtream.http:blueprint", "/api/v1/xtream"),),
    subscriptions=(
        SubscriptionSpec(
            PasswordChanged.NAME, "xtream.revoke_on_password_change", "app.modules.xtream.handlers:on_password_changed"
        ),
        SubscriptionSpec(
            ProfileDeleted.NAME, "xtream.revoke_profile_credentials", "app.modules.xtream.handlers:on_profile_deleted"
        ),
    ),
    error_map={
        CredentialNotFoundError: (404, "XTREAM_CREDENTIAL_NOT_FOUND"),
        CredentialLimitReachedError: (409, "XTREAM_CREDENTIAL_LIMIT"),
        KidsProfileManagementError: (403, "XTREAM_KIDS_PROFILE"),
        ProfileNotOwnedError: (404, "XTREAM_PROFILE_NOT_FOUND"),
        ProfileLockedError: (403, "XTREAM_PROFILE_LOCKED"),
    },
)
