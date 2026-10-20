"""Playback HTTP adapter: /api/v1/playback."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from flask import Blueprint, Response, request, stream_with_context
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.profile_context import current_profile
from app.kernel.resilience.rate_limit import Rate, client_ip
from app.kernel.security.auth import current_user
from app.kernel.security.device_keys import HEADER as DEVICE_HEADER
from app.modules.playback.api import GrantVerifier, PlaybackWindow
from app.modules.playback.hls_proxy import HlsProxyService
from app.modules.playback.services import EVENT_TYPES, PlaybackSessionService

blueprint = Blueprint("playback", __name__)

EventType = Literal["play", "pause", "resume", "seek", "stop", "complete", "error"]
assert set(EventType.__args__) == EVENT_TYPES  # type: ignore[attr-defined]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


#: The longest stretch one catch-up session plays (a long film or match, with margins).
MAX_WINDOW = timedelta(hours=6)


class WindowIn(_Strict):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _sane(self) -> WindowIn:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > MAX_WINDOW:
            raise ValueError("a window is at most 6 hours")
        return self


class OpenSessionRequest(_Strict):
    content_ref: str = Field(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]{1,31}:\d+$")
    window: WindowIn | None = Field(
        default=None, description="Catch-up / start over: a stretch of a live channel's archive (ADR-0012)"
    )


class ContentInfo(BaseModel):
    ref: str
    title: str
    kind: str


class OpenSessionResponse(BaseModel):
    session_token: str
    manifest_url: str
    mime_type: str
    is_live: bool
    drm: dict[str, str] | None
    heartbeat_interval_s: int
    expires_at: int
    content: ContentInfo


class SessionTokenRequest(_Strict):
    session_token: str = Field(min_length=10, max_length=64)


class StatusResponse(BaseModel):
    status: str


class LimitsResponse(BaseModel):
    active_streams: int


class EventRequest(_Strict):
    content_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}:\d+$", max_length=64)
    event_type: EventType
    position_s: int = Field(default=0, ge=0, le=7 * 24 * 3600)
    session_token: str | None = Field(default=None, max_length=64)


class QoeRequest(_Strict):
    content_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}:\d+$", max_length=64)
    session_token: str | None = Field(default=None, max_length=64)
    startup_time_ms: int | None = Field(default=None, ge=0, le=600_000)
    rebuffer_count: int = Field(default=0, ge=0, le=100_000)
    rebuffer_duration_ms: int = Field(default=0, ge=0, le=86_400_000)
    watch_duration_s: int = Field(default=0, ge=0, le=7 * 86_400)
    bitrate_kbps: int | None = Field(default=None, ge=0, le=200_000)
    resolution: str | None = Field(default=None, max_length=20)
    device_type: str | None = Field(default=None, max_length=20)
    connection_type: str | None = Field(default=None, max_length=20)


class CreatedResponse(BaseModel):
    id: int


def _service() -> PlaybackSessionService:
    return resolve(PlaybackSessionService)


@blueprint.post("/sessions")
@endpoint(
    summary="Authorise playback and open a session (returns signed media URLs)",
    profile=True,
    rate=Rate("playback.open", rps=3, burst=5),
    idempotency="playback.open",
    body=OpenSessionRequest,
    response=OpenSessionResponse,
    status=201,
    errors=(
        "STREAM_LIMIT_EXCEEDED",
        "CONTENT_NOT_FOUND",
        "CONTENT_NOT_ALLOWED_FOR_KIDS",
        "PLAYBACK_DENIED",
        "CATCHUP_NOT_AVAILABLE",
        "CATCHUP_NOT_IN_PLAN",
        "CATCHUP_TOO_OLD",
        "CATCHUP_NOT_STARTED",
    ),
)
def open_session(body: OpenSessionRequest) -> OpenSessionResponse:
    opened = _service().open(
        user_id=current_user.id,
        profile=current_profile(),
        content_ref=body.content_ref,
        client_device_id=request.headers.get(DEVICE_HEADER),
        ip=client_ip(),
        user_agent=request.headers.get("User-Agent", ""),
        window=PlaybackWindow(body.window.start, body.window.end) if body.window else None,
    )
    return OpenSessionResponse(
        session_token=opened.token,
        manifest_url=opened.source.manifest_url,
        mime_type=opened.source.mime_type,
        is_live=opened.source.is_live,
        drm=opened.source.drm,
        heartbeat_interval_s=opened.heartbeat_interval_s,
        expires_at=opened.expires_at,
        content=ContentInfo(ref=str(opened.descriptor.ref), title=opened.descriptor.title, kind=opened.descriptor.kind),
    )


@blueprint.post("/sessions/heartbeat")
@endpoint(
    summary="Keep a playback session alive",
    body=SessionTokenRequest,
    response=StatusResponse,
    rate=Rate("playback.heartbeat", rps=1, burst=5),
    errors=("SESSION_EXPIRED",),
)
def heartbeat(body: SessionTokenRequest) -> StatusResponse:
    _service().heartbeat(user_id=current_user.id, token=body.session_token)
    return StatusResponse(status="ok")


@blueprint.post("/sessions/release")
@endpoint(
    auth="public",
    summary="Release a playback slot (token-scoped; usable from navigator.sendBeacon)",
    body=SessionTokenRequest,
    response=StatusResponse,
    rate=Rate("playback.release", rps=5, burst=20, per="ip"),
)
def release(body: SessionTokenRequest) -> StatusResponse:
    released = _service().release(body.session_token, reason="client")
    return StatusResponse(status="released" if released else "unknown")


@blueprint.get("/limits")
@endpoint(summary="Active streams of the current account", response=LimitsResponse)
def limits() -> LimitsResponse:
    return LimitsResponse(active_streams=_service().active_for_user(current_user.id))


@blueprint.post("/events")
@endpoint(
    summary="Record a playback event",
    profile=True,
    body=EventRequest,
    status=201,
    rate=Rate("playback.events", rps=5, burst=20),
)
def record_event(body: EventRequest) -> object:
    _service().record_event(
        user_id=current_user.id,
        profile_id=current_profile().profile_id,
        content_ref=body.content_ref,
        event_type=body.event_type,
        position_s=body.position_s,
        session_token=body.session_token,
    )
    return None


@blueprint.post("/qoe")
@endpoint(
    summary="Record quality-of-experience metrics",
    body=QoeRequest,
    response=CreatedResponse,
    status=201,
    rate=Rate("playback.qoe", rps=1, burst=5),
)
def record_qoe(body: QoeRequest) -> CreatedResponse:
    return CreatedResponse(id=_service().record_qoe(user_id=current_user.id, data=body.model_dump()))


@blueprint.get("/proxy")
@endpoint(
    auth="public",
    summary="Signed upstream media proxy (grant in query string; no credentials needed)",
    rate=Rate("playback.proxy", rps=40, burst=120, per="ip"),
    errors=("GRANT_INVALID", "GRANT_EXPIRED", "SESSION_INACTIVE", "UPSTREAM_STATUS", "UPSTREAM_UNAVAILABLE"),
)
def proxy() -> Response:
    verifier: GrantVerifier = resolve(GrantVerifier)
    grant = verifier.verify(request.args, require_live_session=False)
    service = resolve(HlsProxyService)
    target_is_playlist = ".m3u8" in grant.target.lower() or grant.target.lower().split("?", 1)[0].endswith(".m3u")
    if target_is_playlist:
        verifier.verify(request.args, require_live_session=True)  # playlists re-check the live session
    result = service.fetch(grant, range_header=request.headers.get("Range"))
    body = result.body if isinstance(result.body, bytes) else stream_with_context(result.body)
    response = Response(
        body, status=result.status, mimetype=result.mimetype, direct_passthrough=not isinstance(result.body, bytes)
    )
    for name, value in result.headers.items():
        response.headers[name] = value
    return response
