"""PUBLIC surface of the drm module.

Extension point ``drm.license_issuers`` (declared by drm): one issuer per
:class:`~app.modules.drm.domain.DrmSystem`. A vendor integration (Widevine
proxy, PlayReady, FairPlay SPC/CKC, a multi-DRM SaaS) is a class implementing
:class:`LicenseIssuer` plus one ``ExtensionSpec`` line in the contributing
module's manifest — the drm module itself is not edited.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

POINT_LICENSE_ISSUERS = "drm.license_issuers"


@dataclass(frozen=True, slots=True)
class LicenseRestrictions:
    max_resolution: str
    require_hdcp: bool
    allow_screen_capture: bool
    allow_offline: bool
    offline_validity_h: int


@dataclass(frozen=True, slots=True)
class LicenseRequest:
    system: str
    challenge: bytes
    key_id: str  # hex KID
    content_key: bytes  # clear key: in-process only, never logged or persisted
    restrictions: LicenseRestrictions
    expires_at: datetime
    user_id: int
    session_token: str


@dataclass(frozen=True, slots=True)
class IssuedLicense:
    body: bytes
    media_type: str


class LicenseIssuer(Protocol):
    system: str

    def issue(self, request: LicenseRequest) -> IssuedLicense: ...


@dataclass(frozen=True, slots=True)
class DrmStatsView:
    protected_contents: int
    active_licenses: int
    issued_24h: int
    denied_24h: int
    keys_delivered_24h: int


class DrmStats(Protocol):
    """Capability ``drm.stats`` (admin dashboard)."""

    def stats(self) -> DrmStatsView: ...


__all__ = [
    "POINT_LICENSE_ISSUERS",
    "DrmStats",
    "DrmStatsView",
    "IssuedLicense",
    "LicenseIssuer",
    "LicenseRequest",
    "LicenseRestrictions",
]
