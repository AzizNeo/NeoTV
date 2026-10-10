"""Stateless authentication contract.

The kernel defines *what* an authenticated principal is and *when* it is
resolved (lazily, once per request). *How* a request is authenticated is a
capability provided by a module (``identity.authentication``), which
registers an :class:`AuthenticationBackend` in the container.

No server-side session, no cookie-based identity for API calls: there is no
``login_user`` and therefore no hybrid cookie/bearer identity (SEC-05).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from flask import g, has_request_context, request
from werkzeug.local import LocalProxy

_PRINCIPAL_ATTR = "_kernel_principal"


@runtime_checkable
class Principal(Protocol):
    id: int
    username: str
    role: str
    token_version: int

    @property
    def is_authenticated(self) -> bool: ...

    def has_permission(self, permission: str) -> bool: ...


class AnonymousPrincipal:
    id = None
    username = "anonymous"
    role = "anonymous"
    token_version = 0
    is_authenticated = False

    def has_permission(self, permission: str) -> bool:
        return False


ANONYMOUS = AnonymousPrincipal()


class AuthenticationBackend(Protocol):
    def authenticate(self, req: Any) -> Principal | None: ...


def current_principal() -> Any:
    if not has_request_context():
        return ANONYMOUS
    cached = g.get(_PRINCIPAL_ATTR)
    if cached is not None:
        return cached
    from app.kernel.container import resolve

    principal = resolve(AuthenticationBackend).authenticate(request) or ANONYMOUS
    setattr(g, _PRINCIPAL_ATTR, principal)
    return principal


def set_principal(principal: Any) -> None:
    """Used after login/refresh in the same request (e.g. to scope rate limits)."""
    setattr(g, _PRINCIPAL_ATTR, principal)


current_user: Any = LocalProxy(current_principal)


def login_required(fn: Callable[..., Any]) -> Callable[..., Any]:
    from app.kernel.http.errors import ApiError

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not current_principal().is_authenticated:
            raise ApiError("AUTH_REQUIRED", 401, "Authentication required")
        return fn(*args, **kwargs)

    return wrapper
