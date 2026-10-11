"""Event consumers of the identity module."""

from __future__ import annotations

from app.kernel.container import resolve
from app.kernel.uow import UnitOfWork
from app.modules.identity.notices import SecurityNotices
from app.modules.identity.recovery import AccountRecoveryService
from app.modules.identity.repository import RefreshTokenRepository
from app.shared_kernel.events import DeviceRevoked, EmailChanged, NewDeviceSignedIn, PasswordChanged, UserRegistered


def on_device_revoked(event: DeviceRevoked, *, uow: UnitOfWork) -> None:
    """A revoked device must not be able to mint new access tokens."""
    RefreshTokenRepository(uow.session).revoke_user(event.user_id, device_key=event.device_key)


def on_user_registered(event: UserRegistered, *, uow: UnitOfWork) -> None:
    """Send the verification mail asynchronously — never part of the signup transaction."""
    if event.email:
        resolve(AccountRecoveryService).send_verification_after_signup(uow, event.user_id)


def on_password_changed(event: PasswordChanged, *, uow: UnitOfWork) -> None:
    """Tell the owner — the only defence against a silent takeover is that the real owner finds out."""
    resolve(SecurityNotices).password_changed(uow, event)


def on_email_changed(event: EmailChanged, *, uow: UnitOfWork) -> None:
    """The old inbox learns about the change and gets the undo link."""
    resolve(AccountRecoveryService).notify_email_changed(uow, event)


def on_new_device_signed_in(event: NewDeviceSignedIn, *, uow: UnitOfWork) -> None:
    """devices noticed an unknown device; identity owns the address, so identity tells the owner."""
    resolve(SecurityNotices).new_device(uow, event)
