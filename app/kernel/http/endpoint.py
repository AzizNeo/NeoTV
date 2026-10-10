"""``endpoint()`` — one decorator that composes every HTTP concern in a fixed,
correct order (DECORATOR_ORDER.md enforced *by construction*):

    tracing → authentication → rate limit → permission → profile context
            → idempotency → request validation → handler → response contract

and records OpenAPI metadata. Handlers receive validated Pydantic models as
``body=`` / ``query=`` keyword arguments and may return a Pydantic model,
plain data or a Flask ``Response``. When ``response=`` is declared, the return
value is validated against it — a handler cannot silently drift from the
published contract.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from flask import Response, request
from pydantic import BaseModel, TypeAdapter

from app.kernel.http.profile_context import require_profile_context
from app.kernel.http.responses import ok
from app.kernel.observability.tracing import traced
from app.kernel.resilience.idempotency import idempotent
from app.kernel.resilience.rate_limit import Rate, client_ip, rate_limited
from app.kernel.security.auth import current_principal, login_required
from app.kernel.security.permissions import require_permission

Auth = Literal["public", "user"]


@dataclass(frozen=True)
class EndpointDoc:
    summary: str
    tags: tuple[str, ...]
    auth: Auth
    permission: str | None
    profile: bool
    idempotency: str | None
    body: type[BaseModel] | None
    query: type[BaseModel] | None
    response: Any
    status: int
    rate: Rate | None
    deprecated: bool = False
    errors: tuple[str, ...] = field(default_factory=tuple)


_ADAPTERS: dict[Any, TypeAdapter[Any]] = {}


def _adapter(tp: Any) -> TypeAdapter[Any]:
    adapter = _ADAPTERS.get(tp)
    if adapter is None:
        adapter = TypeAdapter(tp)
        _ADAPTERS[tp] = adapter
    return adapter


def _parse_body(model: type[BaseModel]) -> BaseModel:
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    return model.model_validate(payload)


def _parse_query(model: type[BaseModel]) -> BaseModel:
    return model.model_validate(request.args.to_dict(flat=True))


def _serialize(result: Any, response_type: Any) -> Any:
    if response_type is not None:
        adapter = _adapter(response_type)
        return adapter.dump_python(adapter.validate_python(result, from_attributes=True), mode="json")
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list) and result and isinstance(result[0], BaseModel):
        return [item.model_dump(mode="json") for item in result]
    return result


def _user_identity() -> str:
    principal = current_principal()
    return f"user:{principal.id}" if principal.is_authenticated else f"ip:{client_ip()}"


def endpoint(
    *,
    auth: Auth = "user",
    summary: str = "",
    tags: tuple[str, ...] = (),
    rate: Rate | None = None,
    permission: str | None = None,
    profile: bool = False,
    idempotency: str | None = None,
    body: type[BaseModel] | None = None,
    query: type[BaseModel] | None = None,
    response: Any = None,
    status: int = 200,
    deprecated: bool = False,
    errors: tuple[str, ...] = (),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    if auth == "public" and (permission or profile):
        raise ValueError("a public endpoint cannot require a permission or a profile")
    if rate is not None and rate.per == "user" and auth == "public":
        raise ValueError("per-user rate limit on a public endpoint; use Rate(per='ip')")

    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(handler)
        def invoke(*args: Any, **kwargs: Any) -> Any:
            if body is not None:
                kwargs["body"] = _parse_body(body)
            if query is not None:
                kwargs["query"] = _parse_query(query)
            result = handler(*args, **kwargs)
            if isinstance(result, Response | tuple):
                return result
            return ok(_serialize(result, response), status=status)

        wrapped: Callable[..., Any] = invoke
        if idempotency:
            wrapped = idempotent(idempotency)(wrapped)
        if profile:
            wrapped = require_profile_context(wrapped)
        if permission:
            wrapped = require_permission(permission)(wrapped)
        if rate is not None:
            identity = _user_identity if rate.per == "user" else (lambda: f"ip:{client_ip()}")
            wrapped = rate_limited(rate, identity)(wrapped)
        if auth == "user":
            wrapped = login_required(wrapped)
        wrapped = traced(f"{handler.__module__}.{handler.__qualname__}")(wrapped)

        wrapped.__endpoint_doc__ = EndpointDoc(  # type: ignore[attr-defined]
            summary=summary or (handler.__doc__ or "").strip().split("\n")[0],
            tags=tags,
            auth=auth,
            permission=permission,
            profile=profile,
            idempotency=idempotency,
            body=body,
            query=query,
            response=response,
            status=status,
            rate=rate,
            deprecated=deprecated,
            errors=errors,
        )
        return wrapped

    return decorator
