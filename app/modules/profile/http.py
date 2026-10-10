"""Profile HTTP adapter: /api/v1/profiles."""

from __future__ import annotations

from flask import Blueprint
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.profile_context import current_profile
from app.kernel.http.responses import no_content
from app.kernel.resilience.rate_limit import Rate
from app.kernel.security.auth import current_user
from app.modules.profile.services import ProfileService

blueprint = Blueprint("profile", __name__)

AVATARS = ("default", "red", "blue", "green", "yellow", "purple", "kids-bear", "kids-rocket")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileOut(BaseModel):
    id: int
    name: str
    avatar: str
    is_kids: bool
    is_default: bool
    has_pin: bool


class CreateProfileRequest(_Strict):
    name: str = Field(min_length=1, max_length=40)
    avatar: str = Field(default="default", pattern="^(" + "|".join(AVATARS) + ")$")
    is_kids: bool = False


class UpdateProfileRequest(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    avatar: str | None = Field(default=None, pattern="^(" + "|".join(AVATARS) + ")$")
    is_kids: bool | None = None


class SelectProfileRequest(_Strict):
    pin: str | None = Field(default=None, max_length=8)


class SelectProfileResponse(BaseModel):
    profile_token: str
    profile: ProfileOut


class SetPinRequest(_Strict):
    pin: str = Field(min_length=4, max_length=8)
    current_pin: str | None = Field(default=None, max_length=8)


class ClearPinRequest(_Strict):
    current_pin: str | None = Field(default=None, max_length=8)


def _service() -> ProfileService:
    return resolve(ProfileService)


@blueprint.get("")
@endpoint(summary="List profiles of the account", response=list[ProfileOut])
def list_profiles() -> list:
    return _service().list(current_user.id)


@blueprint.post("")
@endpoint(
    summary="Create a profile",
    body=CreateProfileRequest,
    response=ProfileOut,
    status=201,
    errors=("PROFILE_LIMIT_REACHED", "PROFILE_NAME_TAKEN"),
)
def create_profile(body: CreateProfileRequest) -> object:
    return _service().create(user_id=current_user.id, name=body.name, avatar=body.avatar, is_kids=body.is_kids)


@blueprint.get("/current")
@endpoint(summary="The profile bound to this request", profile=True, response=ProfileOut)
def get_current() -> object:
    return _service().get_owned(current_user.id, current_profile().profile_id)


@blueprint.patch("/<int:profile_id>")
@endpoint(summary="Update a profile", body=UpdateProfileRequest, response=ProfileOut)
def update_profile(profile_id: int, body: UpdateProfileRequest) -> object:
    return _service().update(
        user_id=current_user.id, profile_id=profile_id, name=body.name, avatar=body.avatar, is_kids=body.is_kids
    )


@blueprint.delete("/<int:profile_id>")
@endpoint(summary="Delete a profile", errors=("DEFAULT_PROFILE_PROTECTED",))
def delete_profile(profile_id: int) -> object:
    _service().delete(user_id=current_user.id, profile_id=profile_id)
    return no_content()


@blueprint.post("/<int:profile_id>/select")
@endpoint(
    summary="Select a profile and obtain a profile context token",
    body=SelectProfileRequest,
    response=SelectProfileResponse,
    rate=Rate("profile.select", rps=1, burst=5),
    errors=("PIN_REQUIRED", "PIN_INVALID", "PIN_LOCKED"),
)
def select_profile(profile_id: int, body: SelectProfileRequest) -> SelectProfileResponse:
    token, profile = _service().select(
        user_id=current_user.id, token_version=current_user.token_version, profile_id=profile_id, pin=body.pin
    )
    return SelectProfileResponse(profile_token=token, profile=ProfileOut.model_validate(profile, from_attributes=True))


@blueprint.put("/<int:profile_id>/pin")
@endpoint(
    summary="Set or change a profile PIN",
    body=SetPinRequest,
    response=ProfileOut,
    rate=Rate("profile.pin", rps=0.5, burst=3),
)
def set_pin(profile_id: int, body: SetPinRequest) -> object:
    return _service().set_pin(
        user_id=current_user.id, profile_id=profile_id, pin=body.pin, current_pin=body.current_pin
    )


@blueprint.delete("/<int:profile_id>/pin")
@endpoint(
    summary="Remove a profile PIN",
    body=ClearPinRequest,
    response=ProfileOut,
    rate=Rate("profile.pin", rps=0.5, burst=3),
)
def clear_pin(profile_id: int, body: ClearPinRequest) -> object:
    return _service().clear_pin(user_id=current_user.id, profile_id=profile_id, current_pin=body.current_pin)
