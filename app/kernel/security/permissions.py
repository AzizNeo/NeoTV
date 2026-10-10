"""Permission catalog: modules *declare* the permissions they enforce.

Roles (owned by the identity module) may only grant declared permissions —
validated at boot, so a typo in a role definition is a named boot error
instead of a silently ungranted right.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable
from typing import Any

from app.kernel.errors import DuplicatePermissionError, UnknownPermissionError

WILDCARD = "*"


class PermissionCatalog:
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def declare(self, permission: str, owner: str) -> None:
        if permission in self._owners:
            raise DuplicatePermissionError(permission, self._owners[permission], owner)
        self._owners[permission] = owner

    def assert_known(self, permissions: Iterable[str], *, context: str) -> None:
        unknown = sorted(p for p in permissions if p != WILDCARD and p not in self._owners)
        if unknown:
            raise UnknownPermissionError(f"{context} references undeclared permission(s): {unknown}")

    def all(self) -> dict[str, str]:
        return dict(sorted(self._owners.items()))


def require_permission(permission: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    from app.kernel.http.errors import ApiError
    from app.kernel.security.auth import current_principal

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            principal = current_principal()
            if not principal.is_authenticated:
                raise ApiError("AUTH_REQUIRED", 401, "Authentication required")
            if not principal.has_permission(permission):
                raise ApiError("PERMISSION_DENIED", 403, f"Missing permission '{permission}'")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
