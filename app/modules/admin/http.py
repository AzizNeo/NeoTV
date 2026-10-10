"""Admin HTTP adapter: /api/v1/admin (permission ``admin:access``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from flask import Blueprint
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.responses import no_content
from app.kernel.security.auth import current_user
from app.modules.admin.services import AbuseService, AdminService

blueprint = Blueprint("admin", __name__)

_TAGS = ("admin",)
_PERM = "admin:access"


class DashboardOut(BaseModel):
    users: dict[str, int]
    sessions: dict[str, int]
    catalog: dict[str, int] | None
    live: dict[str, int] | None
    devices: dict[str, int] | None
    plans: dict[str, int] | None
    drm: dict[str, int] | None
    generated_at: str


class UsersQuery(BaseModel):
    cursor: int | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=100)
    search: str | None = Field(default=None, max_length=80)


class AdminUserOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    plan: str | None
    active_sessions: int
    created_at: datetime
    last_login_at: datetime | None


class AdminUserPageOut(BaseModel):
    items: list[AdminUserOut]
    next_cursor: int | None


class SessionsQuery(BaseModel):
    limit: int = Field(default=200, ge=1, le=1000)


class LiveSessionOut(BaseModel):
    token: str
    user_id: int
    profile_id: int
    content_ref: str
    ip: str | None
    user_agent: str | None
    started_at: datetime
    last_heartbeat_at: datetime


class FlagsQuery(BaseModel):
    status: Literal["open", "dismissed", "actioned"] = "open"
    limit: int = Field(default=100, ge=1, le=500)


class ResolveFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["dismissed", "actioned"]


class FlagOut(BaseModel):
    id: int
    user_id: int
    kind: str
    score: int
    details: str
    status: str
    first_seen_at: datetime
    last_seen_at: datetime


def _admin() -> AdminService:
    return resolve(AdminService)


@blueprint.get("/stats")
@endpoint(
    summary="Dashboard (sections of disabled modules are null)", tags=_TAGS, permission=_PERM, response=DashboardOut
)
def stats() -> Any:
    return _admin().dashboard()


@blueprint.get("/users")
@endpoint(
    summary="Users (cursor pagination)", tags=_TAGS, permission=_PERM, query=UsersQuery, response=AdminUserPageOut
)
def users(query: UsersQuery) -> Any:
    return _admin().users(cursor=query.cursor, limit=query.limit, search=query.search)


@blueprint.post("/users/<int:user_id>/suspend")
@endpoint(
    summary="Suspend an account (ends its sessions and streams)",
    tags=_TAGS,
    permission=_PERM,
    response=AdminUserOut,
    errors=("USER_NOT_FOUND", "PROTECTED_ACCOUNT"),
)
def suspend(user_id: int) -> Any:
    return _admin().set_active(user_id=user_id, active=False, actor_id=current_user.id)


@blueprint.post("/users/<int:user_id>/activate")
@endpoint(
    summary="Re-activate an account", tags=_TAGS, permission=_PERM, response=AdminUserOut, errors=("USER_NOT_FOUND",)
)
def activate(user_id: int) -> Any:
    return _admin().set_active(user_id=user_id, active=True, actor_id=current_user.id)


@blueprint.get("/sessions/live")
@endpoint(
    summary="Live playback sessions", tags=_TAGS, permission=_PERM, query=SessionsQuery, response=list[LiveSessionOut]
)
def live_sessions(query: SessionsQuery) -> Any:
    return _admin().live_sessions(query.limit)


@blueprint.post("/sessions/<token>/terminate")
@endpoint(summary="Terminate a playback session", tags=_TAGS, permission=_PERM, errors=("SESSION_NOT_FOUND",))
def terminate(token: str) -> Any:
    _admin().terminate_session(token)
    return no_content()


@blueprint.get("/abuse/flags")
@endpoint(summary="Abuse flags", tags=_TAGS, permission=_PERM, query=FlagsQuery, response=list[FlagOut])
def abuse_flags(query: FlagsQuery) -> Any:
    return resolve(AbuseService).flags(status=query.status, limit=query.limit)


@blueprint.post("/abuse/flags/<int:flag_id>/resolve")
@endpoint(
    summary="Resolve an abuse flag",
    tags=_TAGS,
    permission=_PERM,
    body=ResolveFlag,
    response=FlagOut,
    errors=("ABUSE_FLAG_NOT_FOUND",),
)
def resolve_flag(flag_id: int, body: ResolveFlag) -> Any:
    return resolve(AbuseService).resolve(flag_id, outcome=body.outcome, actor_id=current_user.id)
