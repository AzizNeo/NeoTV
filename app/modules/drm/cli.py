"""``flask drm ...`` commands."""

from __future__ import annotations

import click
from flask.cli import AppGroup

from app.kernel.container import resolve
from app.modules.drm.services import ProtectionService

drm_cli = AppGroup("drm", help="DRM key custody.")


@drm_cli.command("rewrap-keys")
def rewrap_keys() -> None:
    """KEK rotation: put the new Fernet key FIRST in DRM_KEK_KEYS (keep the old
    ones after it), run this, then remove the old keys."""
    count = resolve(ProtectionService).rewrap_all()
    click.echo(f"re-wrapped {count} content key(s) with the newest KEK")


@drm_cli.command("generate-kek")
def generate_kek() -> None:
    """Print a new Fernet key for DRM_KEK_KEYS."""
    from cryptography.fernet import Fernet

    click.echo(Fernet.generate_key().decode())
