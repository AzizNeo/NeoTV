"""``flask kernel ...`` — introspection and scaffolding commands."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import click
from flask import current_app
from flask.cli import AppGroup

from app.kernel.container import resolve
from app.kernel.events.bus import EventBus
from app.kernel.extensions import ExtensionRegistry
from app.kernel.http.openapi import build_openapi
from app.kernel.security.permissions import PermissionCatalog
from app.kernel.settings import PROJECT_ROOT

kernel_cli = AppGroup("kernel", help="Kernel introspection and scaffolding.")


@kernel_cli.command("modules")
def modules_command() -> None:
    """List installed modules, their capabilities and dependencies."""
    registry = current_app.extensions["module_registry"]
    click.echo(json.dumps(registry.describe(), indent=2))


@kernel_cli.command("graph")
def graph_command() -> None:
    """Print events → consumers, extension points → contributors, permissions → owners."""
    click.echo(
        json.dumps(
            {
                "events": resolve(EventBus).describe(),
                "extension_points": resolve(ExtensionRegistry).describe(),
                "permissions": resolve(PermissionCatalog).all(),
            },
            indent=2,
        )
    )


@kernel_cli.command("openapi")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), default=None)
def openapi_command(out: Path | None) -> None:
    """Dump the OpenAPI document (stdout or --out)."""
    document = json.dumps(build_openapi(current_app), indent=2, sort_keys=False) + "\n"
    if out is None:
        click.echo(document, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(document, encoding="utf-8")
        click.echo(f"written {out}")


def scaffold_module(name: str, *, modules_dir: Path | None = None) -> Path:
    """Copy ``app/modules/_template`` to ``app/modules/<name>`` with every
    spelling of the placeholder (module path, UPPER error codes, CamelCase
    classes) replaced. Raises ``ValueError`` / ``FileExistsError``."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name):
        raise ValueError("module name must be snake_case (2-31 chars)")
    modules_dir = modules_dir or PROJECT_ROOT / "app" / "modules"
    target = modules_dir / name
    if target.exists():
        raise FileExistsError(f"{target} already exists")
    shutil.copytree(modules_dir / "_template", target, ignore=shutil.ignore_patterns("__pycache__"))
    camel = "".join(part.capitalize() for part in name.split("_"))
    replacements = (("_template", name), ("_TEMPLATE", name.upper()), ("Template", camel))
    for path in [*target.rglob("*.py"), *target.rglob("*.md")]:
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
    return target


@kernel_cli.command("new-module")
@click.argument("name")
def new_module_command(name: str) -> None:
    """Scaffold app/modules/<name> from app/modules/_template."""
    try:
        target = scaffold_module(name)
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    except FileExistsError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"created {target}")
    click.echo(f'next: add "app.modules.{name}" to INSTALLED_MODULES in app/modules/__init__.py')
