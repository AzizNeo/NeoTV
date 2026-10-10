"""Event consumers of the identity module."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.identity.recovery import AccountRecoveryService
from app.modules.identity.repository import RefreshTokenRepository
from app.shared_kernel.events import DeviceRevoked, UserRegistered


def on_device_revoked(event: DeviceRevoked, *, uow: UnitOfWork) -> None:
    """A revoked device must not be able to mint new access tokens."""
    RefreshTokenRepository(uow.session).revoke_user(event.user_id, device_key=event.device_key)


def on_user_registered(event: UserRegistered, *, uow: UnitOfWork) -> None:
    """Send the verification mail asynchronously — never part of the signup transaction."""
    if event.email:
        resolve(AccountRecoveryService).send_verification_after_signup(uow, event.user_id)
