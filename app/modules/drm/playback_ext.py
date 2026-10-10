"""DRM contributions to the playback gate (extension points owned by playback).

* ``DrmDevicePolicy`` (``playback.policies``): a protected content's policy may
  restrict device classes — evaluated before a stream slot is taken.
* ``DrmSourceEnhancer`` (``playback.source_enhancers``): attaches session-bound
  key / license URLs to the resolved source. Unprotected content is untouched.
"""

from __future__ import annotations

from typing import Any

from app.modules.drm.domain import DrmSystem, DrmSystemUnavailableError
from app.modules.drm.services import IssuerRegistry, LicenseService, ProtectionService, key_path, license_path
from app.modules.playback.api import (
    ContentDescriptor,
    Deny,
    PlaybackContext,
    ResolvedSource,
    StreamUrlFactory,
)
from app.shared_kernel.user_agent import parse_user_agent


class DrmDevicePolicy:
    name = "drm_device_class"
    order = 40

    def __init__(self, protection: ProtectionService) -> None:
        self._protection = protection

    def evaluate(self, ctx: PlaybackContext, descriptor: ContentDescriptor) -> Deny | None:
        info = self._protection.lookup(str(ctx.content))
        if info is None or not info.policy.allowed_device_classes:
            return None
        device_class = parse_user_agent(ctx.user_agent).device_type
        if device_class not in info.policy.allowed_device_classes:
            return Deny("DEVICE_CLASS_NOT_ALLOWED", f"This content cannot be played on a {device_class} device")
        return None


class DrmSourceEnhancer:
    name = "drm"

    def __init__(
        self, protection: ProtectionService, licenses: LicenseService, urls: StreamUrlFactory, issuers: IssuerRegistry
    ) -> None:
        self._protection = protection
        self._licenses = licenses
        self._urls = urls
        self._issuers = issuers

    def enhance(self, ctx: PlaybackContext, descriptor: ContentDescriptor, source: ResolvedSource) -> ResolvedSource:
        info = self._protection.lookup(str(ctx.content))
        if info is None:
            return source
        restrictions = self._licenses.restrictions(ctx.user_id, info.policy)
        drm: dict[str, str] = {
            "key_id": info.key_id,
            "max_resolution": restrictions.max_resolution,  # ABR ceiling hint; the license enforces it
        }
        usable: list[str] = []
        if DrmSystem.AES_128 in info.systems:
            drm["aes-128.key_uri"] = self._urls.signed(key_path(info.key_id), ctx)
            usable.append(str(DrmSystem.AES_128))
        available = self._issuers.available()
        for system in sorted(s for s in info.systems if s.uses_license_server):
            if str(system) in available:
                drm[f"{system}.license_url"] = self._urls.signed(license_path(str(system)), ctx)
                usable.append(str(system))
        if not usable:
            raise DrmSystemUnavailableError(
                f"content '{ctx.content}' is protected with {sorted(map(str, info.systems))} but no issuer is installed"
            )
        drm["systems"] = ",".join(usable)
        return source.with_drm(drm)


def build_device_policy(c: Any) -> DrmDevicePolicy:
    return DrmDevicePolicy(c.resolve(ProtectionService))


def build_source_enhancer(c: Any) -> DrmSourceEnhancer:
    return DrmSourceEnhancer(
        c.resolve(ProtectionService), c.resolve(LicenseService), c.resolve(StreamUrlFactory), c.resolve(IssuerRegistry)
    )
