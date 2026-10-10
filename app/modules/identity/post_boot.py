from __future__ import annotations

from typing import Any

from app.kernel.security.permissions import PermissionCatalog
from app.modules.identity.domain import ROLE_PERMISSIONS


def validate_roles(container: Any, _app: Any) -> None:
    """Roles may only grant permissions some installed module declared."""
    catalog = container.resolve(PermissionCatalog)
    for role, permissions in ROLE_PERMISSIONS.items():
        catalog.assert_known(permissions, context=f"role '{role}'")
