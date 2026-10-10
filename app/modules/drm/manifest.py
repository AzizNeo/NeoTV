from __future__ import annotations

from typing import Any

from app.kernel.capabilities import CapabilityIndex
from app.kernel.extensions import ExtensionRegistry
from app.kernel.manifest import ExtensionSpec, ModuleManifest, RouteSpec, SubscriptionSpec
from app.kernel.settings import Settings
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.drm.api import POINT_LICENSE_ISSUERS, DrmStats
from app.modules.drm.domain import (
    AlreadyProtectedError,
    DrmConfigurationError,
    DrmSystemNotEnabledError,
    DrmSystemUnavailableError,
    KeyNotFoundError,
    KeyVaultError,
    LicenseChallengeError,
    LicenseNotFoundError,
    PolicyInUseError,
    PolicyNameTakenError,
    PolicyNotFoundError,
    ProtectedContentNotFoundError,
    UnknownContentError,
)
from app.modules.drm.vault import KeyVault
from app.modules.playback.api import ContentDirectory, SessionDirectory
from app.shared_kernel.events import ContentRemoved, PlaybackSessionEnded


def _services(c: Any) -> None:
    from app.modules.drm.services import (
        DrmMonitoringService,
        IssuerRegistry,
        LicenseService,
        PolicyService,
        ProtectionService,
    )
    from app.modules.drm.vault import build_key_vault

    c.register(KeyVault, lambda c: build_key_vault(c.resolve(Settings)))
    c.register(
        IssuerRegistry, lambda c: IssuerRegistry(lambda: c.resolve(ExtensionRegistry).build(POINT_LICENSE_ISSUERS, c))
    )
    c.register(PolicyService, lambda c: PolicyService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(
        ProtectionService,
        lambda c: ProtectionService(
            c.resolve(UnitOfWorkFactory), c.resolve(KeyVault), c.resolve(Clock), c.resolve(ContentDirectory)
        ),
    )
    c.register(
        LicenseService,
        lambda c: LicenseService(
            uow=c.resolve(UnitOfWorkFactory),
            vault=c.resolve(KeyVault),
            clock=c.resolve(Clock),
            sessions=c.resolve(SessionDirectory),
            issuers=c.resolve(IssuerRegistry),
            capabilities=c.resolve(CapabilityIndex),
        ),
    )
    c.register(DrmMonitoringService, lambda c: DrmMonitoringService(c.resolve(UnitOfWorkFactory), c.resolve(Clock)))
    c.register(DrmStats, lambda c: c.resolve(DrmMonitoringService))


manifest = ModuleManifest(
    name="drm",
    version="2.0.0",
    description="Envelope-encrypted content keys, session-bound licenses, AES-128 key delivery, pluggable issuers.",
    provides={"drm.stats": DrmStats},
    requires=frozenset(
        {"identity.authentication", "playback.urls", "playback.grants", "playback.content", "playback.sessions"}
    ),
    optional_requires=frozenset({"billing.entitlements"}),
    models=("app.modules.drm.models",),
    services=_services,
    routes=(RouteSpec("app.modules.drm.http:blueprint", "/api/v1/drm"),),
    extension_points=(POINT_LICENSE_ISSUERS,),
    extensions=(
        ExtensionSpec(POINT_LICENSE_ISSUERS, "app.modules.drm.issuers:build_clearkey_issuer"),
        ExtensionSpec("playback.policies", "app.modules.drm.playback_ext:build_device_policy"),
        ExtensionSpec("playback.source_enhancers", "app.modules.drm.playback_ext:build_source_enhancer"),
    ),
    subscriptions=(
        SubscriptionSpec(
            PlaybackSessionEnded.NAME,
            "drm.release_session_licenses",
            "app.modules.drm.handlers:on_playback_session_ended",
        ),
        SubscriptionSpec(
            ContentRemoved.NAME, "drm.shred_removed_content", "app.modules.drm.handlers:on_content_removed"
        ),
    ),
    task_modules=("app.modules.drm.tasks",),
    beat_schedule={
        "drm.expire-licenses": {"task": "drm.expire_licenses", "schedule": 120.0},
        "drm.purge-events": {"task": "drm.purge_events", "schedule": 86_400.0},
    },
    permissions=("drm:admin", "drm:keys"),
    cli=("app.modules.drm.cli:drm_cli",),
    post_boot="app.modules.drm.post_boot:validate_routes",
    error_map={
        ProtectedContentNotFoundError: (404, "DRM_CONTENT_NOT_FOUND"),
        AlreadyProtectedError: (409, "DRM_ALREADY_PROTECTED"),
        UnknownContentError: (404, "DRM_UNKNOWN_CONTENT"),
        PolicyNotFoundError: (404, "DRM_POLICY_NOT_FOUND"),
        PolicyNameTakenError: (409, "DRM_POLICY_NAME_TAKEN"),
        PolicyInUseError: (409, "DRM_POLICY_IN_USE"),
        DrmSystemNotEnabledError: (422, "DRM_SYSTEM_NOT_ENABLED"),
        DrmSystemUnavailableError: (503, "DRM_SYSTEM_UNAVAILABLE"),
        KeyNotFoundError: (404, "DRM_KEY_NOT_FOUND"),
        LicenseChallengeError: (400, "DRM_CHALLENGE_INVALID"),
        LicenseNotFoundError: (404, "DRM_LICENSE_NOT_FOUND"),
        KeyVaultError: (500, "DRM_KEY_VAULT_ERROR"),
        DrmConfigurationError: (500, "DRM_MISCONFIGURED"),
    },
)
