"""Event consumers: credentials follow the account's password and the profile they are bound to."""

from __future__ import annotations

from datetime import datetime

from app.kernel.uow import UnitOfWork
from app.modules.xtream.services import CredentialService
from app.shared_kernel.events import PasswordChanged, ProfileDeleted


def on_password_changed(event: PasswordChanged, *, uow: UnitOfWork) -> None:
    # Like app passwords elsewhere: a new account password (a reset above all) ends every TV app's access.
    CredentialService.revoke_for_user(uow.session, event.user_id, datetime.fromisoformat(event.occurred_at))


def on_profile_deleted(event: ProfileDeleted, *, uow: UnitOfWork) -> None:
    CredentialService.revoke_for_profile(uow.session, event.profile_id, datetime.fromisoformat(event.occurred_at))
