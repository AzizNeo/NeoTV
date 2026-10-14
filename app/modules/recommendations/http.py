"""Recommendations HTTP adapter: /api/v1/recommendations (profile-scoped)."""

from __future__ import annotations

from flask import Blueprint
from pydantic import BaseModel, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.profile_context import current_profile
from app.kernel.resilience.rate_limit import Rate
from app.modules.recommendations.services import RecommendationService

blueprint = Blueprint("recommendations", __name__)

_TAGS = ("recommendations",)


class RecoCardOut(BaseModel):
    ref: str
    title: str
    image: str | None
    group: str | None
    kind: str
    rating: str
    reason: str  # English sentence (kept for older clients); display from the code below
    reason_code: str  # trending | recommended | likes_group | watched
    reason_subject: str | None = None  # the genre / title the reason refers to


class RowOut(BaseModel):
    key: str  # for_you | trending | because:<ref>
    title: str  # English (kept for older clients); clients word the row from key + subject
    subject: str | None = None
    items: list[RecoCardOut]


class RowQuery(BaseModel):
    limit: int = Field(default=12, ge=1, le=50)


class TrendingQuery(RowQuery):
    hours: int = Field(default=24, ge=1, le=24 * 30)


def _svc() -> RecommendationService:
    return resolve(RecommendationService)


@blueprint.get("/home")
@endpoint(
    summary="Home rows (For You, Because you watched, Trending)",
    tags=_TAGS,
    profile=True,
    query=RowQuery,
    response=list[RowOut],
    rate=Rate("reco.home", rps=3, burst=10),
    errors=("TEMPORARILY_UNAVAILABLE",),
)
def home(query: RowQuery) -> object:
    ctx = current_profile()
    return _svc().home(profile_id=ctx.profile_id, is_kids=ctx.is_kids, limit=query.limit)


@blueprint.get("/trending")
@endpoint(
    summary="Trending now",
    tags=_TAGS,
    profile=True,
    query=TrendingQuery,
    response=RowOut,
    rate=Rate("reco.trending", rps=5, burst=20),
    errors=("TEMPORARILY_UNAVAILABLE",),
)
def trending(query: TrendingQuery) -> object:
    return _svc().trending(is_kids=current_profile().is_kids, hours=query.hours, limit=query.limit)


@blueprint.get("/for-you")
@endpoint(
    summary="Personalised for the current profile",
    tags=_TAGS,
    profile=True,
    query=RowQuery,
    response=RowOut,
    rate=Rate("reco.for_you", rps=3, burst=10),
)
def for_you(query: RowQuery) -> object:
    ctx = current_profile()
    return _svc().for_you(profile_id=ctx.profile_id, is_kids=ctx.is_kids, limit=query.limit)
