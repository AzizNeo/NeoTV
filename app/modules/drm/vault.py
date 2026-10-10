"""Content-key custody — envelope encryption (SEC-07).

Content keys are never stored in clear: each is wrapped with a key-encryption
key (KEK). ``FernetKeyVault`` uses ``MultiFernet`` so KEKs rotate without
downtime: the first key wraps, every key unwraps, ``rewrap`` migrates rows.
Production can swap in a KMS / Vault-Transit adapter implementing the same
``KeyVault`` protocol (one class + one line in the manifest).
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.modules.drm.domain import KeyVaultError


class KeyVault(Protocol):
    def wrap(self, plaintext_key: bytes) -> str: ...
    def unwrap(self, wrapped: str) -> bytes: ...
    def rewrap(self, wrapped: str) -> str: ...


class FernetKeyVault:
    def __init__(self, keys: list[bytes]) -> None:
        if not keys:
            raise ValueError("KeyVault requires at least one KEK (DRM_KEK_KEYS)")
        self._fernet = MultiFernet([Fernet(k) for k in keys])

    def wrap(self, plaintext_key: bytes) -> str:
        return self._fernet.encrypt(plaintext_key).decode()

    def unwrap(self, wrapped: str) -> bytes:
        try:
            return self._fernet.decrypt(wrapped.encode())
        except InvalidToken as exc:
            raise KeyVaultError("content key cannot be unwrapped with the configured KEKs") from exc

    def rewrap(self, wrapped: str) -> str:
        try:
            return self._fernet.rotate(wrapped.encode()).decode()
        except InvalidToken as exc:
            raise KeyVaultError("content key cannot be re-wrapped with the configured KEKs") from exc


def build_key_vault(settings: Any) -> FernetKeyVault:
    """Prod: ``DRM_KEK_KEYS`` (comma separated Fernet keys, newest first) — enforced
    by Settings. Dev/test: a KEK derived from SECRET_KEY (purpose-bound)."""
    if settings.drm_kek_keys:
        return FernetKeyVault([k.get_secret_value().encode() for k in settings.drm_kek_keys])
    derived = base64.urlsafe_b64encode(settings.derive_key("drm.kek")[:32])
    return FernetKeyVault([derived])
