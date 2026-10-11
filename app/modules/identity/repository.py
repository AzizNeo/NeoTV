from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy import true as sa_true
from sqlalchemy.orm import Session

from app.kernel.time import utcnow
from app.modules.identity.models import ActionToken, RefreshToken, User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, user_id: int) -> User | None:
        return self._s.get(User, user_id)

    def by_username(self, username: str) -> User | None:
        return self._s.execute(
            select(User).where(func.lower(User.username) == username.strip().lower())
        ).scalar_one_or_none()

    def username_exists(self, username: str) -> bool:
        return self.by_username(username) is not None

    def by_email(self, email: str) -> User | None:
        return self._s.execute(select(User).where(func.lower(User.email) == email.strip().lower())).scalar_one_or_none()

    def email_exists(self, email: str) -> bool:
        return (
            self._s.execute(select(User.id).where(func.lower(User.email) == email.strip().lower())).first() is not None
        )

    def add(self, user: User) -> User:
        self._s.add(user)
        self._s.flush([user])
        return user

    def page(self, *, cursor: int | None, limit: int, search: str | None) -> list[User]:
        stmt = select(User).order_by(User.id.asc()).limit(limit)
        if cursor:
            stmt = stmt.where(User.id > cursor)
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(or_(func.lower(User.username).like(like), func.lower(User.email).like(like)))
        return list(self._s.execute(stmt).scalars())

    def counts(self, since: datetime) -> tuple[int, int, int]:
        total = self._s.execute(select(func.count(User.id))).scalar_one()
        active = self._s.execute(select(func.count(User.id)).where(User.is_active.is_(True))).scalar_one()
        new = self._s.execute(select(func.count(User.id)).where(User.created_at >= since)).scalar_one()
        return int(total), int(active), int(new)


class RefreshTokenRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, token: RefreshToken) -> None:
        self._s.add(token)

    def by_hash(self, token_hash: str, *, for_update: bool = False) -> RefreshToken | None:
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        if for_update:
            stmt = stmt.with_for_update()
        return self._s.execute(stmt).scalar_one_or_none()

    def revoke_family(self, family_id: str) -> int:
        result = self._s.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        return int(result.rowcount or 0)

    def revoke_user(self, user_id: int, *, device_key: str | None = None) -> int:
        stmt = update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        if device_key is not None:
            stmt = stmt.where(RefreshToken.device_key == device_key)
        return int(self._s.execute(stmt.values(revoked_at=utcnow())).rowcount or 0)


class ActionTokenRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def add(self, token: ActionToken) -> ActionToken:
        self._s.add(token)
        self._s.flush([token])
        return token

    def by_hash(self, token_hash: str, purpose: str) -> ActionToken | None:
        return self._s.execute(
            select(ActionToken)
            .where(ActionToken.token_hash == token_hash, ActionToken.purpose == purpose)
            .with_for_update()
        ).scalar_one_or_none()

    def latest_created_at(self, user_id: int, purpose: str) -> datetime | None:
        return self._s.execute(
            select(func.max(ActionToken.created_at)).where(
                ActionToken.user_id == user_id, ActionToken.purpose == purpose
            )
        ).scalar_one()

    def consume_open(self, user_id: int, purpose: str, now: datetime) -> int:
        """Mark every still-open token of this purpose as used (supersede / burn)."""
        result = self._s.execute(
            update(ActionToken)
            .where(ActionToken.user_id == user_id, ActionToken.purpose == purpose, ActionToken.used_at.is_(None))
            .values(used_at=now)
        )
        return int(result.rowcount or 0)

    def consume_all_open(self, user_id: int, now: datetime, *, keep: frozenset[str] = frozenset()) -> int:
        """Burn every open link of the account except the purposes in ``keep``."""
        result = self._s.execute(
            update(ActionToken)
            .where(
                ActionToken.user_id == user_id,
                ActionToken.used_at.is_(None),
                ActionToken.purpose.not_in(keep) if keep else sa_true(),
            )
            .values(used_at=now)
        )
        return int(result.rowcount or 0)

    def consume_open_since(self, user_id: int, purpose: str, since: datetime, now: datetime) -> int:
        """Burn open links of ``purpose`` created at/after ``since`` (later links in a chain)."""
        result = self._s.execute(
            update(ActionToken)
            .where(
                ActionToken.user_id == user_id,
                ActionToken.purpose == purpose,
                ActionToken.used_at.is_(None),
                ActionToken.created_at >= since,
            )
            .values(used_at=now)
        )
        return int(result.rowcount or 0)
