from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.http.profile_context import ProfileContextResolver
from app.kernel.manifest import ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.security.tokens import TokenService
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.profile.api import ProfileDirectory
from app.modules.profile.services import (
    DefaultProfileProtectedError,
    PinFormatError,
    PinInvalidError,
    PinLockedError,
    PinRequiredError,
    ProfileLimitReachedError,
    ProfileNameTakenError,
    ProfileNotFoundError,
)
from app.shared_kernel.events import UserRegistered


def _services(c: Any) -> None:
    from app.modules.profile.services import ProfileDirectoryService, ProfileService, TokenProfileContextResolver

    c.register(
        ProfileService,
        lambda c: ProfileService(
            uow=c.resolve(UnitOfWorkFactory),
            tokens=c.resolve(TokenService),
            redis=c.resolve("kernel.redis"),
            clock=c.resolve(Clock),
            capabilities=c.resolve(CapabilityIndex),
        ),
    )
    c.register(ProfileDirectory, lambda c: ProfileDirectoryService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(
        ProfileContextResolver,
        lambda c: TokenProfileContextResolver(
            c.resolve(TokenService), c.resolve(ProfileDirectory), c.resolve(Settings).profile_context_mode
        ),
    )


manifest = ModuleManifest(
    name="profile",
    version="2.0.0",
    description="Viewer profiles per account, PIN lock, profile context tokens.",
    provides={"profile.context": ProfileContextResolver, "profile.directory": ProfileDirectory},
    requires=frozenset({"identity.authentication"}),
    optional_requires=frozenset({"billing.entitlements"}),
    models=("app.modules.profile.models",),
    services=_services,
    routes=(RouteSpec("app.modules.profile.http:blueprint", "/api/v1/profiles"),),
    subscriptions=(
        SubscriptionSpec(
            UserRegistered.NAME, "profile.create_default", "app.modules.profile.handlers:on_user_registered"
        ),
    ),
    error_map={
        ProfileNotFoundError: (404, "PROFILE_NOT_FOUND"),
        ProfileLimitReachedError: (403, "PROFILE_LIMIT_REACHED"),
        ProfileNameTakenError: (409, "PROFILE_NAME_TAKEN"),
        DefaultProfileProtectedError: (409, "DEFAULT_PROFILE_PROTECTED"),
        PinRequiredError: (401, "PIN_REQUIRED"),
        PinInvalidError: (401, "PIN_INVALID"),
        PinFormatError: (422, "PIN_FORMAT"),
        PinLockedError: (429, "PIN_LOCKED"),
    },
)
