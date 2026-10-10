"""DRM HTTP adapter: /api/v1/drm.

Player endpoints are *public* but grant-protected: the signed URL minted by
playback for one session is the credential (EME license requests and HLS key
fetches cannot reliably carry bearer tokens). Admin endpoints require
``drm:admin``; exporting a clear content key additionally requires ``drm:keys``.
"""

from __future__ import annotations

import re
from datetime import datetime

from flask import Blueprint, Response, request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.errors import ApiError
from app.kernel.http.responses import no_content, ok
from app.kernel.resilience.rate_limit import Rate, client_ip
from app.kernel.security.auth import current_user
from app.modules.drm.domain import DeviceClass, DrmEventType, DrmSystem, Resolution
from app.modules.drm.services import (
    DrmMonitoringService,
    LicenseService,
    PolicyInput,
    PolicyService,
    ProtectionService,
)
from app.modules.playback.api import GrantVerifier

blueprint = Blueprint("drm", __name__)

_TAGS = ("drm",)
_ADMIN = "drm:admin"
_KID = re.compile(r"[0-9a-f]{32}")
MAX_CHALLENGE_BYTES = 64 * 1024
_NO_STORE = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── Schemas ────────────────────────────────────────────────────────────────


class ProtectRequest(_Strict):
    content_ref: str = Field(pattern=r"^[a-z][a-z0-9_]{1,30}:[1-9][0-9]{0,18}$")
    systems: list[DrmSystem] = Field(min_length=1, max_length=5)
    policy_id: int | None = Field(default=None, ge=1)


class ProtectionPatch(_Strict):
    systems: list[DrmSystem] | None = Field(default=None, min_length=1, max_length=5)
    policy_id: int | None = Field(default=None, ge=1)
    clear_policy: bool = False

    @model_validator(mode="after")
    def _exclusive(self) -> ProtectionPatch:
        if self.clear_policy and self.policy_id is not None:
            raise ValueError("policy_id and clear_policy are mutually exclusive")
        return self


class ProtectedContentOut(BaseModel):
    id: int
    content_ref: str
    title: str | None
    key_id: str
    systems: list[str]
    policy_id: int | None
    active_licenses: int
    key_rotated_at: datetime | None
    created_at: datetime


class ProtectedContentPage(BaseModel):
    items: list[ProtectedContentOut]
    total: int
    page: int
    per_page: int


class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1, le=10_000)
    per_page: int = Field(default=50, ge=1, le=200)


class KeyExportOut(BaseModel):
    content_ref: str
    key_id: str
    key_hex: str
    key_uri: str
    systems: list[str]


class PolicyCreate(_Strict):
    name: str = Field(min_length=1, max_length=50)
    max_resolution: Resolution = Resolution.P2160
    license_duration_s: int = Field(default=600, ge=60, le=86_400)
    allow_offline: bool = False
    offline_validity_h: int = Field(default=48, ge=1, le=720)
    allowed_device_classes: list[DeviceClass] = Field(default_factory=list, max_length=5)
    require_hdcp: bool = False
    allow_screen_capture: bool = False
    is_default: bool = False


class PolicyPatch(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    max_resolution: Resolution | None = None
    license_duration_s: int | None = Field(default=None, ge=60, le=86_400)
    allow_offline: bool | None = None
    offline_validity_h: int | None = Field(default=None, ge=1, le=720)
    allowed_device_classes: list[DeviceClass] | None = Field(default=None, max_length=5)
    require_hdcp: bool | None = None
    allow_screen_capture: bool | None = None
    is_default: bool | None = None


class PolicyOut(BaseModel):
    id: int
    name: str
    max_resolution: str
    license_duration_s: int
    allow_offline: bool
    offline_validity_h: int
    allowed_device_classes: list[str]
    require_hdcp: bool
    allow_screen_capture: bool
    is_default: bool
    created_at: datetime


class LicenseOut(BaseModel):
    id: str
    user_id: int
    content_ref: str
    system: str
    status: str
    max_resolution: str | None
    renewals: int
    ip: str | None
    issued_at: datetime
    expires_at: datetime


class LimitQuery(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class EventsQuery(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)
    type: DrmEventType | None = None
    before_id: int | None = Field(default=None, ge=1)


class EventOut(BaseModel):
    id: int
    event_type: str
    user_id: int | None
    content_ref: str | None
    license_id: str | None
    system: str | None
    error_code: str | None
    detail: str | None
    ip: str | None
    created_at: datetime


class StatsOut(BaseModel):
    protected_contents: int
    active_licenses: int
    issued_24h: int
    denied_24h: int
    keys_delivered_24h: int


# ── Player endpoints (grant-protected) ─────────────────────────────────────


@blueprint.get("/keys/<key_id>")
@endpoint(
    auth="public",
    summary="HLS AES-128 key delivery (session-bound signed URL)",
    tags=_TAGS,
    rate=Rate("drm.keys", rps=5, burst=30, per="ip"),
    errors=("GRANT_INVALID", "GRANT_EXPIRED", "SESSION_INACTIVE", "DRM_KEY_NOT_FOUND"),
)
def deliver_key(key_id: str) -> Response:
    if not _KID.fullmatch(key_id):
        raise ApiError("DRM_KEY_NOT_FOUND", 404)
    grant = resolve(GrantVerifier).verify(request.args, path=request.path, require_live_session=True)
    key = resolve(LicenseService).deliver_key(grant=grant, key_id=key_id, ip=client_ip())
    response = Response(key, mimetype="application/octet-stream")
    response.headers.update(_NO_STORE)
    return response


@blueprint.post("/licenses/<system>")
@endpoint(
    auth="public",
    summary="EME license (challenge in the raw body; repeated calls renew)",
    tags=_TAGS,
    rate=Rate("drm.licenses", rps=2, burst=10, per="ip"),
    errors=(
        "GRANT_INVALID",
        "SESSION_INACTIVE",
        "DRM_SYSTEM_NOT_ENABLED",
        "DRM_SYSTEM_UNAVAILABLE",
        "DRM_CHALLENGE_INVALID",
    ),
)
def issue_license(system: str) -> Response:
    if request.content_length is not None and request.content_length > MAX_CHALLENGE_BYTES:
        raise ApiError("DRM_CHALLENGE_INVALID", 413, "challenge too large")
    grant = resolve(GrantVerifier).verify(request.args, path=request.path, require_live_session=True)
    challenge = request.get_data(cache=False)[: MAX_CHALLENGE_BYTES + 1]
    if len(challenge) > MAX_CHALLENGE_BYTES:
        raise ApiError("DRM_CHALLENGE_INVALID", 413, "challenge too large")
    issued = resolve(LicenseService).issue_license(grant=grant, system=system, challenge=challenge, ip=client_ip())
    response = Response(issued.body, mimetype=issued.media_type)
    response.headers.update(_NO_STORE)
    return response


# ── Admin: protected content ───────────────────────────────────────────────


@blueprint.get("/admin/contents")
@endpoint(summary="Protected content", tags=_TAGS, permission=_ADMIN, query=PageQuery, response=ProtectedContentPage)
def list_contents(query: PageQuery) -> object:
    items, total = resolve(ProtectionService).page(page=query.page, per_page=query.per_page)
    return {"items": items, "total": total, "page": query.page, "per_page": query.per_page}


@blueprint.post("/admin/contents")
@endpoint(
    summary="Protect content (generates a wrapped content key)",
    tags=_TAGS,
    permission=_ADMIN,
    body=ProtectRequest,
    response=ProtectedContentOut,
    status=201,
    errors=("DRM_ALREADY_PROTECTED", "DRM_UNKNOWN_CONTENT", "DRM_POLICY_NOT_FOUND"),
)
def protect(body: ProtectRequest) -> object:
    return resolve(ProtectionService).protect(
        content_ref=body.content_ref,
        systems=[str(s) for s in body.systems],
        policy_id=body.policy_id,
        actor_id=current_user.id,
    )


@blueprint.get("/admin/contents/<int:content_id>")
@endpoint(summary="Protected content detail", tags=_TAGS, permission=_ADMIN, response=ProtectedContentOut)
def get_content(content_id: int) -> object:
    return resolve(ProtectionService).get(content_id)


@blueprint.patch("/admin/contents/<int:content_id>")
@endpoint(
    summary="Change systems / policy", tags=_TAGS, permission=_ADMIN, body=ProtectionPatch, response=ProtectedContentOut
)
def update_content(content_id: int, body: ProtectionPatch) -> object:
    return resolve(ProtectionService).update(
        content_id,
        systems=[str(s) for s in body.systems] if body.systems is not None else None,
        policy_id=body.policy_id,
        clear_policy=body.clear_policy,
    )


@blueprint.post("/admin/contents/<int:content_id>/rotate-key")
@endpoint(
    summary="Rotate the content key (revokes active licenses; re-package afterwards)",
    tags=_TAGS,
    permission=_ADMIN,
    response=ProtectedContentOut,
)
def rotate_key(content_id: int) -> object:
    return resolve(ProtectionService).rotate_key(content_id, actor_id=current_user.id)


@blueprint.delete("/admin/contents/<int:content_id>")
@endpoint(summary="Remove protection (destroys the key)", tags=_TAGS, permission=_ADMIN)
def unprotect(content_id: int) -> object:
    resolve(ProtectionService).unprotect(content_id, actor_id=current_user.id)
    return no_content()


@blueprint.get("/admin/contents/<int:content_id>/key")
@endpoint(
    summary="Export the clear content key for the packager (audited)",
    tags=_TAGS,
    permission="drm:keys",
    rate=Rate("drm.key_export", rps=0.2, burst=5),
)
def export_key(content_id: int) -> object:
    exported = resolve(ProtectionService).export_key(content_id, actor_id=current_user.id, ip=client_ip())
    return ok(KeyExportOut.model_validate(exported, from_attributes=True).model_dump(mode="json"), headers=_NO_STORE)


# ── Admin: policies ────────────────────────────────────────────────────────


@blueprint.get("/admin/policies")
@endpoint(summary="DRM policies", tags=_TAGS, permission=_ADMIN, response=list[PolicyOut])
def list_policies() -> object:
    return resolve(PolicyService).all()


@blueprint.post("/admin/policies")
@endpoint(
    summary="Create a DRM policy",
    tags=_TAGS,
    permission=_ADMIN,
    body=PolicyCreate,
    response=PolicyOut,
    status=201,
    errors=("DRM_POLICY_NAME_TAKEN",),
)
def create_policy(body: PolicyCreate) -> object:
    return resolve(PolicyService).create(PolicyInput(**body.model_dump(mode="json")))


@blueprint.patch("/admin/policies/<int:policy_id>")
@endpoint(
    summary="Update a DRM policy",
    tags=_TAGS,
    permission=_ADMIN,
    body=PolicyPatch,
    response=PolicyOut,
    errors=("DRM_POLICY_NOT_FOUND", "DRM_POLICY_NAME_TAKEN"),
)
def update_policy(policy_id: int, body: PolicyPatch) -> object:
    return resolve(PolicyService).update(policy_id, body.model_dump(mode="json", exclude_unset=True))


@blueprint.delete("/admin/policies/<int:policy_id>")
@endpoint(
    summary="Delete an unused DRM policy",
    tags=_TAGS,
    permission=_ADMIN,
    errors=("DRM_POLICY_NOT_FOUND", "DRM_POLICY_IN_USE"),
)
def delete_policy(policy_id: int) -> object:
    resolve(PolicyService).delete(policy_id)
    return no_content()


# ── Admin: monitoring ──────────────────────────────────────────────────────


@blueprint.get("/admin/licenses/active")
@endpoint(summary="Active licenses", tags=_TAGS, permission=_ADMIN, query=LimitQuery, response=list[LicenseOut])
def active_licenses(query: LimitQuery) -> object:
    return resolve(DrmMonitoringService).active_licenses(query.limit)


@blueprint.post("/admin/licenses/<license_id>/revoke")
@endpoint(
    summary="Revoke a license", tags=_TAGS, permission=_ADMIN, response=LicenseOut, errors=("DRM_LICENSE_NOT_FOUND",)
)
def revoke_license(license_id: str) -> object:
    return resolve(LicenseService).revoke(license_id, actor_id=current_user.id)


@blueprint.get("/admin/events")
@endpoint(
    summary="DRM audit trail (newest first, keyset pagination)",
    tags=_TAGS,
    permission=_ADMIN,
    query=EventsQuery,
    response=list[EventOut],
)
def events(query: EventsQuery) -> object:
    return resolve(DrmMonitoringService).events(
        limit=query.limit, event_type=str(query.type) if query.type else None, before_id=query.before_id
    )


@blueprint.get("/admin/stats")
@endpoint(summary="DRM statistics (last 24h)", tags=_TAGS, permission=_ADMIN, response=StatsOut)
def stats() -> object:
    return resolve(DrmMonitoringService).stats()
