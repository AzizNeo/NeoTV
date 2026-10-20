"""Live HTTP adapter: /api/v1/live."""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta
from typing import Literal

from flask import Blueprint, Response, make_response, redirect, request, send_from_directory
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator
from werkzeug.wrappers import Response as WerkzeugResponse

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.errors import ApiError
from app.kernel.http.profile_context import current_profile
from app.kernel.http.responses import no_content
from app.kernel.resilience.rate_limit import Rate, client_ip
from app.kernel.security.auth import current_user
from app.kernel.settings import Settings
from app.kernel.task_tracking import TaskTracker
from app.kernel.time import utcnow
from app.modules.live.orchestrator import TranscodeOrchestrator
from app.modules.live.provider import hls_dir
from app.modules.live.services import EpgService, LiveChannelService
from app.modules.live.tasks import stream_dir
from app.modules.live.transcoding import master_playlist
from app.modules.playback.api import GrantVerifier

blueprint = Blueprint("live", __name__)

RatingLiteral = Literal["general", "teen", "adult", "unrated"]
M3U8 = "application/vnd.apple.mpegurl"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProgramOut(BaseModel):
    id: int
    channel_id: int
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime


class LiveChannelOut(BaseModel):
    ref: str
    id: int
    name: str
    description: str | None
    logo: str | None
    is_live: bool
    rating: RatingLiteral
    now: ProgramOut | None
    next: ProgramOut | None


class GuideQuery(BaseModel):
    hours: int = Field(default=6, ge=1, le=48)
    start: datetime | None = None
    channel_ids: str | None = Field(default=None, max_length=500)

    @field_validator("channel_ids")
    @classmethod
    def _ids(cls, value: str | None) -> str | None:
        if value and not all(part.strip().isdigit() for part in value.split(",")):
            raise ValueError("channel_ids must be comma separated integers")
        return value


class LiveChannelAdminOut(BaseModel):
    id: int
    ref: str
    name: str
    description: str | None
    logo: str | None
    source_type: Literal["external", "ingest"]
    upstream_url: str | None
    delivery: Literal["proxy", "direct"]
    playback_id: str
    ingest_key_last4: str | None
    epg_channel_id: str | None
    rating: RatingLiteral
    sort_order: int
    is_live: bool
    is_active: bool
    archive_days: int = Field(description="Catch-up archive in days; 0 = not recorded (ADR-0012)")
    archive_confirmed_by: int | None = Field(description="Administrator who switched the archive on")
    archive_confirmed_at: datetime | None


class ArchiveRequest(_Strict):
    days: int = Field(ge=0, description="0 switches the archive off")
    rights_confirmed: bool = Field(
        default=False,
        description="External sources only: the operator holds the rights to record this stream",
    )


class CreateLiveChannelRequest(_Strict):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    logo: AnyHttpUrl | None = None
    source_type: Literal["external", "ingest"] = "external"
    upstream_url: AnyHttpUrl | None = None
    delivery: Literal["proxy", "direct"] = "proxy"
    rating: RatingLiteral = "unrated"
    epg_channel_id: str | None = Field(default=None, max_length=128)
    sort_order: int = Field(default=0, ge=0, le=100_000)


class UpdateLiveChannelRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    logo: AnyHttpUrl | None = None
    upstream_url: AnyHttpUrl | None = None
    delivery: Literal["proxy", "direct"] | None = None
    rating: RatingLiteral | None = None
    epg_channel_id: str | None = Field(default=None, max_length=128)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    is_active: bool | None = None


class CreatedLiveChannelOut(BaseModel):
    channel: LiveChannelAdminOut
    ingest_key: str | None = Field(description="Shown exactly once for ingest channels")


class IngestKeyOut(BaseModel):
    channel_id: int
    ingest_key: str


class ProgramRequest(_Strict):
    channel_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    starts_at: datetime
    ends_at: datetime


class EpgImportRequest(_Strict):
    url: AnyHttpUrl


class TaskAccepted(BaseModel):
    task_id: str


# ── Viewer endpoints ───────────────────────────────────────────────────────
@blueprint.get("/channels")
@endpoint(summary="Live channels with now/next programme", profile=True, response=list[LiveChannelOut])
def list_channels() -> object:
    return resolve(LiveChannelService).list_public(kids_only=current_profile().is_kids)


@blueprint.get("/guide")
@endpoint(summary="Programme guide window", query=GuideQuery, response=list[ProgramOut])
def guide(query: GuideQuery) -> object:
    start = query.start or (utcnow() - timedelta(hours=1))
    ids = [int(x) for x in query.channel_ids.split(",")] if query.channel_ids else None
    return resolve(EpgService).guide(start=start, end=start + timedelta(hours=query.hours), channel_ids=ids)


@blueprint.get("/hls/<playback_id>/<path:filename>")
@endpoint(auth="public", summary="Transcoded HLS (grant-protected)", rate=Rate("live.hls", rps=40, burst=120, per="ip"))
def hls_asset(playback_id: str, filename: str) -> Response:
    if not playback_id.isalnum() or len(playback_id) > 32:
        raise ApiError("NOT_FOUND", 404)
    is_playlist = filename.endswith(".m3u8")
    grant = resolve(GrantVerifier).verify(request.args, require_live_session=is_playlist)
    if grant.target != hls_dir(playback_id):
        raise ApiError("GRANT_INVALID", 403, "Grant does not cover this stream")
    settings = resolve(Settings)
    query = request.query_string.decode()

    if filename == "master.m3u8":
        resolve(TranscodeOrchestrator).touch(playback_id)
        return _playlist_response(_append_query(master_playlist(), query))

    directory = stream_dir(settings, playback_id)
    if is_playlist:
        if not _is_variant(filename):
            raise ApiError("NOT_FOUND", 404)
        resolve(TranscodeOrchestrator).touch(playback_id)
        path = directory / filename
        if not path.is_file():
            response = make_response("", 503)
            response.headers["Retry-After"] = "1"
            return response
        return _playlist_response(_append_query(path.read_text(encoding="utf-8", errors="replace"), query))

    if not _is_segment(filename):
        raise ApiError("NOT_FOUND", 404)
    if settings.hls_serve_via_nginx:
        response = make_response("", 200)
        response.headers["X-Accel-Redirect"] = f"/_protected_hls/{playback_id}/{filename}"
        response.headers["Content-Type"] = "video/mp2t"
        return response
    response = send_from_directory(directory, filename, mimetype="video/mp2t", max_age=30, conditional=True)
    return response


def _is_variant(name: str) -> bool:
    return name.startswith("stream_") and name.endswith(".m3u8") and name[7:-5].isdigit()


def _is_segment(name: str) -> bool:
    folder, _, leaf = name.partition("/")
    return _is_variant(folder + ".m3u8") and leaf.startswith("data") and leaf.endswith(".ts") and leaf[4:-3].isdigit()


def _append_query(playlist: str, query: str) -> str:
    out = []
    for line in playlist.splitlines():
        stripped = line.strip()
        out.append(f"{stripped}?{query}" if stripped and not stripped.startswith("#") else stripped)
    return "\n".join(out) + "\n"


def _playlist_response(body: str) -> Response:
    response = make_response(body, 200)
    response.headers["Content-Type"] = M3U8
    response.headers["Cache-Control"] = "no-store"
    return response


# ── nginx-rtmp callbacks (internal network only) ───────────────────────────
def _require_internal_caller() -> None:
    allowed = resolve(Settings).ingest_callback_allowed_ips
    try:
        caller = ipaddress.ip_address(client_ip())
    except ValueError as exc:
        raise ApiError("FORBIDDEN", 403) from exc
    if not any(caller in ipaddress.ip_network(entry, strict=False) for entry in allowed):
        raise ApiError("FORBIDDEN", 403, "Ingest callbacks are accepted from the RTMP server only")


@blueprint.post("/ingest/on-publish")
@endpoint(auth="public", summary="nginx-rtmp on_publish: verify key, rename stream to playback id")
def ingest_on_publish() -> WerkzeugResponse:
    _require_internal_caller()
    playback_id = resolve(LiveChannelService).on_publish(request.form.get("name", ""))
    return redirect(playback_id, code=302)  # nginx-rtmp: 3xx on publish = rename stream to Location


@blueprint.post("/ingest/on-done")
@endpoint(auth="public", summary="nginx-rtmp on_publish_done")
def ingest_on_done() -> Response:
    _require_internal_caller()
    name = request.form.get("name", "")
    resolve(LiveChannelService).on_done(name)
    resolve(TranscodeOrchestrator).request_stop(name)
    return no_content()


# ── Administration ─────────────────────────────────────────────────────────
@blueprint.get("/admin/channels")
@endpoint(summary="All live channels (admin)", permission="live:write", response=list[LiveChannelAdminOut])
def admin_list() -> object:
    return resolve(LiveChannelService).list_admin()


@blueprint.post("/admin/channels")
@endpoint(
    summary="Create a live channel",
    permission="live:write",
    body=CreateLiveChannelRequest,
    response=CreatedLiveChannelOut,
    status=201,
)
def admin_create(body: CreateLiveChannelRequest) -> object:
    channel, key = resolve(LiveChannelService).create(
        name=body.name,
        description=body.description,
        logo=str(body.logo) if body.logo else None,
        source_type=body.source_type,
        upstream_url=str(body.upstream_url) if body.upstream_url else None,
        delivery=body.delivery,
        rating=body.rating,
        epg_channel_id=body.epg_channel_id,
        sort_order=body.sort_order,
    )
    return {"channel": channel, "ingest_key": key}


@blueprint.patch("/admin/channels/<int:channel_id>")
@endpoint(
    summary="Edit a live channel", permission="live:write", body=UpdateLiveChannelRequest, response=LiveChannelAdminOut
)
def admin_update(channel_id: int, body: UpdateLiveChannelRequest) -> object:
    return resolve(LiveChannelService).update(
        channel_id,
        name=body.name,
        description=body.description,
        logo_url=str(body.logo) if body.logo else None,
        upstream_url=str(body.upstream_url) if body.upstream_url else None,
        delivery=body.delivery,
        rating=body.rating,
        epg_channel_id=body.epg_channel_id,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )


@blueprint.put("/admin/channels/<int:channel_id>/archive")
@endpoint(
    summary="Switch a channel's catch-up archive on or off (external sources need the rights confirmation)",
    permission="live:write",
    body=ArchiveRequest,
    response=LiveChannelAdminOut,
    errors=("LIVE_CHANNEL_NOT_FOUND", "ARCHIVE_INVALID", "ARCHIVE_RIGHTS_REQUIRED"),
)
def admin_set_archive(channel_id: int, body: ArchiveRequest) -> object:
    return resolve(LiveChannelService).set_archive(
        channel_id,
        days=body.days,
        rights_confirmed=body.rights_confirmed,
        actor_id=current_user.id,
        max_days=resolve(Settings).archive_max_days,
    )


@blueprint.delete("/admin/channels/<int:channel_id>")
@endpoint(summary="Remove a live channel", permission="live:write")
def admin_delete(channel_id: int) -> object:
    resolve(LiveChannelService).remove(channel_id)
    return no_content()


@blueprint.post("/admin/channels/<int:channel_id>/rotate-key")
@endpoint(
    summary="Rotate an ingest key (old key stops working immediately)", permission="live:write", response=IngestKeyOut
)
def admin_rotate(channel_id: int) -> object:
    return resolve(LiveChannelService).rotate_ingest_key(channel_id)


@blueprint.post("/admin/epg")
@endpoint(summary="Add a programme", permission="live:write", body=ProgramRequest, response=ProgramOut, status=201)
def admin_add_program(body: ProgramRequest) -> object:
    return resolve(EpgService).add(
        channel_id=body.channel_id,
        title=body.title,
        description=body.description,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
    )


@blueprint.delete("/admin/epg/<int:program_id>")
@endpoint(summary="Delete a programme", permission="live:write")
def admin_delete_program(program_id: int) -> object:
    resolve(EpgService).delete(program_id)
    return no_content()


@blueprint.post("/admin/epg/import")
@endpoint(
    summary="Import an XMLTV guide (async)",
    permission="live:write",
    body=EpgImportRequest,
    response=TaskAccepted,
    status=202,
    rate=Rate("live.epg_import", rps=0.1, burst=2),
)
def admin_import_epg(body: EpgImportRequest) -> object:
    from app.modules.live.tasks import import_epg_from

    return TaskAccepted(
        task_id=resolve(TaskTracker).enqueue(import_epg_from, owner_id=current_user.id, args=(str(body.url),))
    )
