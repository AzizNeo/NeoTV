"""Built-in license issuers."""

from __future__ import annotations

import base64
import json
from typing import Any

from app.modules.drm.api import IssuedLicense, LicenseRequest
from app.modules.drm.domain import DrmSystem, LicenseChallengeError

MAX_CHALLENGE_BYTES = 16 * 1024


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class ClearKeyLicenseIssuer:
    """W3C EME ClearKey (https://www.w3.org/TR/encrypted-media/#clear-key).

    Challenge: ``{"kids": ["<b64url KID>"], "type": "temporary"}``.
    Response:  JWK set with only the KIDs that were asked for *and* belong to
    the session's content. ClearKey gives no hardware protection — enable it
    per content only where that is acceptable (dev, low-value content).
    """

    system = str(DrmSystem.CLEARKEY)

    def issue(self, request: LicenseRequest) -> IssuedLicense:
        if len(request.challenge) > MAX_CHALLENGE_BYTES:
            raise LicenseChallengeError("challenge too large")
        try:
            payload = json.loads(request.challenge)
            requested = payload["kids"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LicenseChallengeError("malformed ClearKey challenge") from exc
        if not isinstance(requested, list) or not all(isinstance(k, str) for k in requested):
            raise LicenseChallengeError("'kids' must be a list of strings")
        own_kid = _b64url(bytes.fromhex(request.key_id))
        if own_kid not in {k.rstrip("=") for k in requested}:
            raise LicenseChallengeError("requested KIDs do not belong to this content")
        body: dict[str, Any] = {
            "keys": [{"kty": "oct", "kid": own_kid, "k": _b64url(request.content_key)}],
            "type": "persistent-license"
            if payload.get("type") == "persistent-license" and request.restrictions.allow_offline
            else "temporary",
        }
        return IssuedLicense(json.dumps(body, separators=(",", ":")).encode(), "application/json")


def build_clearkey_issuer(_container: object) -> ClearKeyLicenseIssuer:
    return ClearKeyLicenseIssuer()
