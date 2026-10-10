"""HMAC-SHA256 signed, subject-bound, expiring URL grants.

Used for media delivery (HLS proxy, HLS assets, DRM key delivery): the
backend *authorises* once, then hands the player self-contained signed URLs
— no headers needed (cross-origin CDNs never see credentials, FE-03), and a
leaked URL is useless for another subject and expires.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode


class SignatureInvalidError(Exception):
    pass


class SignatureExpiredError(Exception):
    pass


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True, slots=True)
class Grant:
    target: str
    subject: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class UrlSigner:
    secret: bytes
    default_ttl: int = 300

    def sign(
        self, target: str, subject: str, *, ttl: int | None = None, expires_at: int | None = None
    ) -> dict[str, str]:
        exp = expires_at if expires_at is not None else int(time.time()) + (ttl or self.default_ttl)
        encoded = _b64e(target.encode())
        return {"u": encoded, "s": subject, "exp": str(exp), "sig": self._mac(encoded, subject, exp)}

    def signed_query(self, target: str, subject: str, **kwargs: int) -> str:
        return urlencode(self.sign(target, subject, **kwargs))

    def verify(self, params: Mapping[str, str]) -> Grant:
        encoded = params.get("u") or ""
        subject = params.get("s") or ""
        signature = params.get("sig") or ""
        try:
            exp = int(params.get("exp", ""))
        except ValueError as exc:
            raise SignatureInvalidError("exp") from exc
        if not encoded or not subject:
            raise SignatureInvalidError("missing")
        if not hmac.compare_digest(self._mac(encoded, subject, exp), signature):
            raise SignatureInvalidError("sig")
        if exp < int(time.time()):
            raise SignatureExpiredError()
        try:
            target = _b64d(encoded).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise SignatureInvalidError("target") from exc
        return Grant(target=target, subject=subject, expires_at=exp)

    def _mac(self, encoded: str, subject: str, exp: int) -> str:
        message = f"{encoded}.{subject}.{exp}".encode()
        return _b64e(hmac.new(self.secret, message, hashlib.sha256).digest())
