"""Signed media URLs bound to (user, playback session) — capability ``playback.urls``
and the grant verifier used by every media endpoint (proxy, HLS assets, DRM keys).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.kernel.security.signed_url import SignatureInvalidError, UrlSigner
from app.modules.playback.api import MediaGrant, PlaybackContext, SessionInactiveError
from app.modules.playback.concurrency import StreamConcurrencyGuard

PROXY_PATH = "/api/v1/playback/proxy"


def _subject(user_id: int, session_token: str) -> str:
    return f"{user_id}.{session_token}"


class SignedStreamUrlFactory:
    def __init__(self, signer: UrlSigner) -> None:
        self._signer = signer

    def proxied(self, upstream_url: str, ctx: PlaybackContext) -> str:
        return f"{PROXY_PATH}?" + self._query(upstream_url, ctx.user_id, ctx.session_token, ctx.grant_expires_at)

    def signed(self, internal_path: str, ctx: PlaybackContext) -> str:
        if not internal_path.startswith("/api/"):
            raise ValueError("signed() is for internal API paths only")
        return f"{internal_path}?" + self._query(internal_path, ctx.user_id, ctx.session_token, ctx.grant_expires_at)

    def signed_entry(self, prefix: str, entry: str, ctx: PlaybackContext) -> str:
        """Grant for a whole directory (HLS master + variants + segments), URL pointing at ``entry``."""
        if not prefix.startswith("/api/") or not prefix.endswith("/"):
            raise ValueError("prefix must be an internal API directory path ending with '/'")
        return f"{prefix}{entry}?" + self._query(prefix, ctx.user_id, ctx.session_token, ctx.grant_expires_at)

    def resign(self, target: str, grant: MediaGrant, *, proxy: bool) -> str:
        query = self._query(target, grant.user_id, grant.session_token, grant.expires_at)
        return f"{PROXY_PATH}?{query}" if proxy else f"{target}?{query}"

    def _query(self, target: str, user_id: int, session_token: str, expires_at: int) -> str:
        return urlencode(self._signer.sign(target, _subject(user_id, session_token), expires_at=expires_at))


class MediaGrantVerifier:
    """Capability ``playback.grants``."""

    def __init__(self, signer: UrlSigner, guard: StreamConcurrencyGuard) -> None:
        self._signer = signer
        self._guard = guard

    def verify(self, params: Any, *, path: str | None = None, require_live_session: bool = False) -> MediaGrant:
        grant = self._signer.verify(params)  # SignatureInvalidError / SignatureExpiredError
        user_part, _, token = grant.subject.partition(".")
        if not user_part.isdigit() or not token:
            raise SignatureInvalidError("subject")
        if path is not None and grant.target != path:
            raise SignatureInvalidError("path")
        if require_live_session and not self._guard.is_active(token):
            raise SessionInactiveError("playback session ended")
        return MediaGrant(user_id=int(user_part), session_token=token, target=grant.target, expires_at=grant.expires_at)
