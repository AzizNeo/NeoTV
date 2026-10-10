"""Profile context contract.

The kernel only defines the shape and the decorator; resolution is the
``profile.context`` capability, registered by the profile module as a
:class:`ProfileContextResolver`. If no module provides it, any endpoint that
asks for a profile fails with a *named* ServiceNotRegisteredError.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from flask import g, request

_ATTR = "_kernel_profile"


@dataclass(frozen=True, slots=True)
class ProfileContext:
    profile_id: int
    user_id: int
    is_kids: bool
    name: str = ""


class ProfileContextResolver(Protocol):
    def resolve(self, req: Any, principal: Any) -> ProfileContext: ...


def require_profile_context(fn: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        from app.kernel.container import resolve
        from app.kernel.security.auth import current_principal

        setattr(g, _ATTR, resolve(ProfileContextResolver).resolve(request, current_principal()))
        return fn(*args, **kwargs)

    return wrapper


class ProfileContextMissingError(RuntimeError):
    pass


def current_profile() -> ProfileContext:
    profile = g.get(_ATTR)
    if profile is None:
        raise ProfileContextMissingError("endpoint did not declare profile=True")
    return profile
