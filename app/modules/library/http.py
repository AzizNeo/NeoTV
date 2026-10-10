"""Library HTTP adapter: /api/v1/library (every endpoint is profile-scoped)."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.profile_context import current_profile
from app.kernel.http.responses import no_content
from app.kernel.resilience.rate_limit import Rate
from app.modules.library.services import LibraryService

blueprint = Blueprint("library", __name__)

_TAGS = ("library",)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardOut(BaseModel):
    ref: str
    title: str
    image: str | None
    group: str | None
    kind: str
    rating: str


class FavoriteOut(BaseModel):
    content: CardOut
    added_at: datetime


class ProgressIn(_Strict):
    position_s: int = Field(ge=0, le=7 * 24 * 3600)
    duration_s: int = Field(default=0, ge=0, le=7 * 24 * 3600)


class ProgressOut(BaseModel):
    content_ref: str
    has_progress: bool
    position_s: int
    duration_s: int
    progress_percent: int
    completed: bool
    updated_at: datetime | None


class ContinueOut(BaseModel):
    content: CardOut
    position_s: int
    duration_s: int
    progress_percent: int
    updated_at: datetime


class HistoryOut(BaseModel):
    id: int
    content: CardOut
    watched_at: datetime
    watched_seconds: int


class PageQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=10_000)


class LimitQuery(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


class HistoryQuery(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    before_id: int | None = Field(default=None, ge=1)


class ClearedOut(BaseModel):
    deleted: int


def _svc() -> LibraryService:
    return resolve(LibraryService)


# The content ref travels in the path as "<namespace>:<id>" (":" is a legal path character).
_REF_RULE = "<content_ref>"


@blueprint.get("/favorites")
@endpoint(
    summary="Favourites of the current profile", tags=_TAGS, profile=True, query=PageQuery, response=list[FavoriteOut]
)
def favorites(query: PageQuery) -> object:
    return _svc().favorites(current_profile(), limit=query.limit, offset=query.offset)


@blueprint.get("/favorites/refs")
@endpoint(
    summary="Content refs favourited by the current profile (for list badges)",
    tags=_TAGS,
    profile=True,
    response=list[str],
)
def favorite_refs() -> object:
    return _svc().favorite_refs(current_profile().profile_id)


@blueprint.put(f"/favorites/{_REF_RULE}")
@endpoint(
    summary="Add a favourite (idempotent)",
    tags=_TAGS,
    profile=True,
    response=FavoriteOut,
    rate=Rate("library.favorites", rps=2, burst=20),
    errors=("LIBRARY_CONTENT_NOT_FOUND", "FAVORITE_LIMIT_REACHED"),
)
def add_favorite(content_ref: str) -> object:
    return _svc().add_favorite(current_profile(), content_ref)


@blueprint.delete(f"/favorites/{_REF_RULE}")
@endpoint(
    summary="Remove a favourite (idempotent)", tags=_TAGS, profile=True, rate=Rate("library.favorites", rps=2, burst=20)
)
def remove_favorite(content_ref: str) -> object:
    _svc().remove_favorite(current_profile(), content_ref)
    return no_content()


@blueprint.get(f"/progress/{_REF_RULE}")
@endpoint(summary="Resume position for one item", tags=_TAGS, profile=True, response=ProgressOut)
def get_progress(content_ref: str) -> object:
    return _svc().progress(current_profile(), content_ref)


@blueprint.put(f"/progress/{_REF_RULE}")
@endpoint(
    summary="Save resume position",
    tags=_TAGS,
    profile=True,
    body=ProgressIn,
    response=ProgressOut,
    rate=Rate("library.progress", rps=1, burst=10),
    errors=("LIBRARY_CONTENT_NOT_FOUND",),
)
def save_progress(content_ref: str, body: ProgressIn) -> object:
    return _svc().save_progress(current_profile(), content_ref, position_s=body.position_s, duration_s=body.duration_s)


@blueprint.delete(f"/progress/{_REF_RULE}")
@endpoint(summary="Forget the resume position (remove from Continue Watching)", tags=_TAGS, profile=True)
def clear_progress(content_ref: str) -> object:
    _svc().clear_progress(current_profile(), content_ref)
    return no_content()


@blueprint.get("/continue")
@endpoint(
    summary="Continue watching (5%–90% watched, most recent first)",
    tags=_TAGS,
    profile=True,
    query=LimitQuery,
    response=list[ContinueOut],
)
def continue_watching(query: LimitQuery) -> object:
    return _svc().continue_watching(current_profile(), limit=query.limit)


@blueprint.get("/history")
@endpoint(
    summary="Watch history (keyset pagination)", tags=_TAGS, profile=True, query=HistoryQuery, response=list[HistoryOut]
)
def history(query: HistoryQuery) -> object:
    return _svc().history(current_profile(), limit=query.limit, before_id=query.before_id)


@blueprint.delete("/history")
@endpoint(summary="Clear watch history of the current profile", tags=_TAGS, profile=True, response=ClearedOut)
def clear_history() -> object:
    return {"deleted": _svc().clear_history(current_profile())}


@blueprint.get("/recent")
@endpoint(summary="Recently watched (distinct)", tags=_TAGS, profile=True, query=LimitQuery, response=list[CardOut])
def recent(query: LimitQuery) -> object:
    return _svc().recent(current_profile(), limit=query.limit)
