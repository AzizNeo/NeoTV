"""PUBLIC surface of the profile module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    id: int
    user_id: int
    name: str
    avatar: str
    is_kids: bool
    is_default: bool
    has_pin: bool


class ProfileDirectory(Protocol):
    def get(self, profile_id: int) -> ProfileSummary | None: ...
    def default_for(self, user_id: int) -> ProfileSummary: ...
    def ids_for_user(self, user_id: int) -> list[int]: ...


__all__ = ["ProfileDirectory", "ProfileSummary"]
