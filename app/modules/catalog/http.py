"""Catalog HTTP adapter: /api/v1/catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from flask import Blueprint
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.profile_context import current_profile
from app.kernel.http.responses import no_content, ok
from app.kernel.resilience.rate_limit import Rate
from app.kernel.security.auth import current_user
from app.kernel.task_tracking import TaskTracker
from app.modules.catalog.services import CatalogAdminService, CatalogQuery, CatalogQueryService

blueprint = Blueprint("catalog", __name__)

Kind = Literal["live", "vod"]
RatingLiteral = Literal["general", "teen", "adult", "unrated"]
Delivery = Literal["proxy", "direct"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChannelCardOut(BaseModel):
    ref: str
    id: int
    name: str
    logo: str | None
    group: str
    kind: Kind
    rating: RatingLiteral


class ChannelPageOut(BaseModel):
    items: list[ChannelCardOut]
    total: int
    page: int
    per_page: int
    pages: int
    degraded: bool


class ChannelListQuery(BaseModel):
    page: int = Field(default=1, ge=1, le=10_000)
    per_page: int = Field(default=24, ge=1, le=200)
    search: str | None = Field(default=None, max_length=100)
    group: str | None = Field(default=None, max_length=128)
    kind: Kind | None = None


class GroupOut(BaseModel):
    name: str
    count: int


class LimitQuery(BaseModel):
    limit: int = Field(default=12, ge=1, le=50)


class ChannelAdminOut(BaseModel):
    id: int
    ref: str
    playlist_id: int
    name: str
    stream_url: str
    logo: str | None
    group: str
    kind: Kind
    rating: RatingLiteral
    delivery: Delivery
    is_active: bool


class ChannelAdminPage(BaseModel):
    items: list[ChannelAdminOut]
    total: int
    page: int
    per_page: int


class AdminListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=50, ge=1, le=200)
    search: str | None = Field(default=None, max_length=100)
    include_inactive: bool = False


class CreateChannelRequest(_Strict):
    name: str = Field(min_length=1, max_length=256)
    stream_url: AnyHttpUrl
    logo: AnyHttpUrl | None = None
    group: str = Field(default="Uncategorized", min_length=1, max_length=128)
    kind: Kind = "live"
    rating: RatingLiteral = "unrated"
    delivery: Delivery = "proxy"


class UpdateChannelRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    logo: AnyHttpUrl | None = None
    group: str | None = Field(default=None, min_length=1, max_length=128)
    kind: Kind | None = None
    rating: RatingLiteral | None = None
    delivery: Delivery | None = None


class PlaylistOut(BaseModel):
    id: int
    name: str
    is_system: bool
    has_source: bool
    channel_count: int
    last_synced_at: datetime | None
    last_sync_status: str | None
    last_sync_error: str | None


class CreatePlaylistRequest(_Strict):
    name: str = Field(min_length=1, max_length=128)
    source_url: AnyHttpUrl | None = None
    sync_now: bool = True


class ImportRequest(_Strict):
    text: str | None = Field(default=None, max_length=5_000_000)
    url: AnyHttpUrl | None = None
    probe: bool = True

    @model_validator(mode="after")
    def _exactly_one(self) -> ImportRequest:
        if bool(self.text) == bool(self.url):
            raise ValueError("provide exactly one of 'text' or 'url'")
        return self


class TaskAccepted(BaseModel):
    task_id: str


def _kids() -> bool:
    return current_profile().is_kids


# ── Browsing (profile-aware: kids profiles only see what they may play) ──────
@blueprint.get("/channels")
@endpoint(
    summary="Browse the catalogue",
    profile=True,
    query=ChannelListQuery,
    response=ChannelPageOut,
    rate=Rate("catalog.browse", rps=10, burst=30),
)
def list_channels(query: ChannelListQuery) -> object:
    return resolve(CatalogQueryService).page(
        CatalogQuery(
            page=query.page,
            per_page=query.per_page,
            search=query.search,
            group=query.group,
            kind=query.kind,
            kids_only=_kids(),
        )
    )


@blueprint.get("/channels/<int:channel_id>")
@endpoint(summary="One channel card", profile=True, response=ChannelCardOut)
def get_channel(channel_id: int) -> object:
    return resolve(CatalogQueryService).get(channel_id, kids_only=_kids())


@blueprint.get("/channels/<int:channel_id>/similar")
@endpoint(summary="Channels from the same group", profile=True, query=LimitQuery, response=list[ChannelCardOut])
def similar(channel_id: int, query: LimitQuery) -> object:
    return resolve(CatalogQueryService).similar(channel_id, query.limit, kids_only=_kids())


@blueprint.get("/groups")
@endpoint(summary="Groups with channel counts", profile=True, response=list[GroupOut])
def groups() -> object:
    return [GroupOut(name=g, count=n) for g, n in resolve(CatalogQueryService).groups(kids_only=_kids())]


# ── Administration ─────────────────────────────────────────────────────────
@blueprint.get("/admin/channels")
@endpoint(
    summary="Admin channel list (includes stream URLs)",
    permission="catalog:write",
    query=AdminListQuery,
    response=ChannelAdminPage,
)
def admin_list(query: AdminListQuery) -> object:
    items, total = resolve(CatalogAdminService).list_channels(
        page=query.page, per_page=query.per_page, search=query.search, include_inactive=query.include_inactive
    )
    return {"items": items, "total": total, "page": query.page, "per_page": query.per_page}


@blueprint.post("/admin/channels")
@endpoint(
    summary="Add a channel manually",
    permission="catalog:write",
    body=CreateChannelRequest,
    response=ChannelAdminOut,
    status=201,
    errors=("DUPLICATE_CHANNEL",),
)
def admin_create(body: CreateChannelRequest) -> object:
    return resolve(CatalogAdminService).add_channel(
        name=body.name,
        stream_url=str(body.stream_url),
        logo=str(body.logo) if body.logo else None,
        group=body.group,
        kind=body.kind,
        rating=body.rating,
        delivery=body.delivery,
    )


@blueprint.patch("/admin/channels/<int:channel_id>")
@endpoint(summary="Edit a channel", permission="catalog:write", body=UpdateChannelRequest, response=ChannelAdminOut)
def admin_update(channel_id: int, body: UpdateChannelRequest) -> object:
    return resolve(CatalogAdminService).update_channel(
        channel_id,
        name=body.name,
        logo_url=str(body.logo) if body.logo else None,
        group_name=body.group,
        kind=body.kind,
        rating=body.rating,
        delivery=body.delivery,
    )


@blueprint.delete("/admin/channels/<int:channel_id>")
@endpoint(summary="Remove a channel (emits content.removed)", permission="catalog:write")
def admin_delete(channel_id: int) -> object:
    resolve(CatalogAdminService).remove_channel(channel_id)
    return no_content()


@blueprint.get("/admin/playlists")
@endpoint(summary="Playlists with channel counts", permission="catalog:write", response=list[PlaylistOut])
def admin_playlists() -> object:
    return resolve(CatalogAdminService).list_playlists()


@blueprint.post("/admin/playlists")
@endpoint(
    summary="Register a playlist source (optionally sync now)",
    permission="catalog:write",
    body=CreatePlaylistRequest,
    status=201,
)
def admin_create_playlist(body: CreatePlaylistRequest) -> object:
    from app.modules.catalog.tasks import sync_playlist

    playlist_id = resolve(CatalogAdminService).create_playlist(
        name=body.name, source_url=str(body.source_url) if body.source_url else None, created_by=current_user.id
    )
    task_id = None
    if body.sync_now and body.source_url:
        task_id = resolve(TaskTracker).enqueue(sync_playlist, owner_id=current_user.id, args=(playlist_id,))
    return ok({"id": playlist_id, "task_id": task_id}, status=201)


@blueprint.delete("/admin/playlists/<int:playlist_id>")
@endpoint(
    summary="Delete a playlist and its channels",
    permission="catalog:write",
    errors=("PLAYLIST_NOT_FOUND", "SYSTEM_PLAYLIST_PROTECTED"),
)
def admin_delete_playlist(playlist_id: int) -> object:
    resolve(CatalogAdminService).delete_playlist(playlist_id)
    return no_content()


@blueprint.post("/admin/playlists/<int:playlist_id>/sync")
@endpoint(
    summary="Re-sync a playlist from its source (async)",
    permission="catalog:write",
    response=TaskAccepted,
    status=202,
    rate=Rate("catalog.sync", rps=0.2, burst=3),
)
def admin_sync(playlist_id: int) -> object:
    from app.modules.catalog.tasks import sync_playlist

    resolve(CatalogAdminService).playlist_source(playlist_id)  # 404 early if unknown
    return TaskAccepted(
        task_id=resolve(TaskTracker).enqueue(sync_playlist, owner_id=current_user.id, args=(playlist_id,))
    )


@blueprint.post("/admin/import")
@endpoint(
    summary="Import M3U text or URL into the Manual playlist (async)",
    permission="catalog:write",
    body=ImportRequest,
    response=TaskAccepted,
    status=202,
    rate=Rate("catalog.import", rps=0.2, burst=3),
)
def admin_import(body: ImportRequest) -> object:
    from app.modules.catalog.tasks import import_entries

    task_id = resolve(TaskTracker).enqueue(
        import_entries,
        owner_id=current_user.id,
        kwargs={"text": body.text, "url": str(body.url) if body.url else None, "probe": body.probe},
    )
    return TaskAccepted(task_id=task_id)
