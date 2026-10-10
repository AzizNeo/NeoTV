"""PUBLIC surface of the identity module. Other modules import only this file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class UserSummary:
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


@dataclass(frozen=True, slots=True)
class UserPage:
    items: list[UserSummary]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class UserCounts:
    total: int
    active: int
    new_last_24h: int


class UserDirectory(Protocol):
    def get(self, user_id: int) -> UserSummary | None: ...
    def exists(self, user_id: int) -> bool: ...


class IdentityAdmin(Protocol):
    def list_users(self, *, cursor: int | None, limit: int, search: str | None) -> UserPage: ...
    def set_active(self, *, user_id: int, active: bool, actor_id: int) -> UserSummary: ...
    def counts(self) -> UserCounts: ...


__all__ = ["IdentityAdmin", "UserCounts", "UserDirectory", "UserPage", "UserSummary"]
