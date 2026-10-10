"""DRM domain vocabulary and rules (pure Python)."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class DrmSystem(StrEnum):
    """How a protected rendition is unlocked on the client.

    * ``aes-128``  — HLS AES-128: the player fetches the raw key from our key
      delivery endpoint with a session-bound signed URL.
    * ``clearkey`` — W3C EME ClearKey: license = JWK set (dev/test, browsers).
    * ``widevine`` / ``playready`` / ``fairplay`` — hardware/CDM-backed; need a
      vendor issuer contributed to ``drm.license_issuers``.
    """

    AES_128 = "aes-128"
    CLEARKEY = "clearkey"
    WIDEVINE = "widevine"
    PLAYREADY = "playready"
    FAIRPLAY = "fairplay"

    @property
    def uses_license_server(self) -> bool:
        return self is not DrmSystem.AES_128


class LicenseStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    REVOKED = "revoked"
    EXPIRED = "expired"


class DrmEventType(StrEnum):
    LICENSE_ISSUED = "license_issued"
    LICENSE_RENEWED = "license_renewed"
    LICENSE_DENIED = "license_denied"
    LICENSE_RELEASED = "license_released"
    LICENSE_REVOKED = "license_revoked"
    KEY_DELIVERED = "key_delivered"
    KEY_EXPORTED = "key_exported"
    KEY_ROTATED = "key_rotated"
    CONTENT_PROTECTED = "content_protected"
    CONTENT_UNPROTECTED = "content_unprotected"


class Resolution(StrEnum):
    """Ordered from lowest to highest (declaration order is the ordering)."""

    P240 = "240p"
    P360 = "360p"
    P480 = "480p"
    P720 = "720p"
    P1080 = "1080p"
    P1440 = "1440p"
    P2160 = "2160p"


class DeviceClass(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    TABLET = "tablet"
    TV = "tv"
    UNKNOWN = "unknown"


RESOLUTIONS: tuple[str, ...] = tuple(r.value for r in Resolution)
DEVICE_CLASSES = frozenset(d.value for d in DeviceClass)


def parse_systems(raw: str | Iterable[str]) -> frozenset[DrmSystem]:
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    systems = frozenset(DrmSystem(item.strip()) for item in items if item and item.strip())
    if not systems:
        raise ValueError("at least one DRM system is required")
    return systems


def format_systems(systems: Iterable[DrmSystem]) -> str:
    return ",".join(sorted(str(s) for s in systems))


def lowest_resolution(*values: str | None) -> str:
    """The most restrictive of the given resolutions (unknown values are ignored)."""
    known = [v for v in values if v in RESOLUTIONS]
    if not known:
        return RESOLUTIONS[-1]
    return min(known, key=RESOLUTIONS.index)


def parse_device_classes(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset()
    classes = frozenset(part.strip() for part in raw.split(",") if part.strip())
    unknown = classes - DEVICE_CLASSES
    if unknown:
        raise ValueError(f"unknown device classes: {sorted(unknown)}")
    return classes


# ── Errors ────────────────────────────────────────────────────────────────


class DrmError(Exception):
    pass


class ProtectedContentNotFoundError(DrmError):
    pass


class AlreadyProtectedError(DrmError):
    pass


class UnknownContentError(DrmError):
    """The content reference does not resolve to existing content."""


class PolicyNotFoundError(DrmError):
    pass


class PolicyNameTakenError(DrmError):
    pass


class PolicyInUseError(DrmError):
    pass


class DrmSystemNotEnabledError(DrmError):
    """The content is not packaged for the requested system."""


class DrmSystemUnavailableError(DrmError):
    """The system is enabled for content but no license issuer is installed."""


class KeyNotFoundError(DrmError):
    pass


class LicenseChallengeError(DrmError):
    pass


class LicenseNotFoundError(DrmError):
    pass


class KeyVaultError(DrmError):
    """A wrapped key cannot be decrypted with any configured KEK."""


class DrmConfigurationError(RuntimeError):
    """Wiring problem (e.g. two issuers for one system) — fails loudly at first use."""
