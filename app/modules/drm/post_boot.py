"""Boot-time contract checks for the drm module."""

from __future__ import annotations

from typing import Any

from app.kernel.errors import ModuleContractError
from app.modules.drm.domain import DrmSystem
from app.modules.drm.services import KEY_PATH_PREFIX, LICENSE_PATH_PREFIX


def validate_routes(container: Any, app: Any) -> None:
    """Signed key/license URLs are built from constants; if the blueprint is
    ever mounted elsewhere every DRM playback would 404 — fail at boot instead."""
    adapter = app.url_map.bind("localhost")
    probes = {
        f"{KEY_PATH_PREFIX}{'0' * 32}": "GET",
        f"{LICENSE_PATH_PREFIX}{DrmSystem.CLEARKEY}": "POST",
    }
    for path, method in probes.items():
        try:
            endpoint, _ = adapter.match(path, method=method)
        except Exception as exc:  # werkzeug NotFound / MethodNotAllowed
            raise ModuleContractError("drm", f"route for signed path '{path}' is not mounted ({exc})") from exc
        if not endpoint.startswith("drm."):
            raise ModuleContractError("drm", f"signed path '{path}' is served by '{endpoint}', not by drm")
