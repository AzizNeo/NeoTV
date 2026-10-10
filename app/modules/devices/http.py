"""Devices HTTP adapter: /api/v1/devices."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, request
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.responses import no_content
from app.kernel.security.auth import current_user
from app.kernel.security.device_keys import HEADER
from app.modules.devices.services import DeviceService

blueprint = Blueprint("devices", __name__)


class DeviceOut(BaseModel):
    id: int
    name: str
    device_type: str
    browser: str | None
    os: str | None
    is_trusted: bool
    is_current: bool
    login_count: int
    last_ip: str | None
    last_seen_at: datetime
    created_at: datetime


class RenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)


def _current_key() -> str:
    return resolve(DeviceService).current_key(
        current_user.id, request.headers.get(HEADER), request.headers.get("User-Agent")
    )


@blueprint.get("")
@endpoint(summary="Active devices of the account", response=list[DeviceOut])
def list_devices() -> object:
    return resolve(DeviceService).list(user_id=current_user.id, current_key=_current_key())


@blueprint.delete("/<int:device_id>")
@endpoint(summary="Revoke a device (its sessions and streams end)", errors=("DEVICE_NOT_FOUND",))
def revoke_device(device_id: int) -> object:
    resolve(DeviceService).revoke(user_id=current_user.id, device_id=device_id)
    return no_content()


@blueprint.post("/<int:device_id>/trust")
@endpoint(summary="Mark a device as trusted", response=DeviceOut)
def trust(device_id: int) -> object:
    return resolve(DeviceService).set_trusted(
        user_id=current_user.id, device_id=device_id, trusted=True, current_key=_current_key()
    )


@blueprint.delete("/<int:device_id>/trust")
@endpoint(summary="Remove trust from a device", response=DeviceOut)
def untrust(device_id: int) -> object:
    return resolve(DeviceService).set_trusted(
        user_id=current_user.id, device_id=device_id, trusted=False, current_key=_current_key()
    )


@blueprint.patch("/<int:device_id>")
@endpoint(summary="Rename a device", body=RenameRequest, response=DeviceOut)
def rename(device_id: int, body: RenameRequest) -> object:
    return resolve(DeviceService).rename(
        user_id=current_user.id, device_id=device_id, name=body.name, current_key=_current_key()
    )
