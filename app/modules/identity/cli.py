"""``flask identity ...`` commands."""

from __future__ import annotations

import os

import click
from flask.cli import AppGroup

from app.kernel.container import resolve
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory
from app.modules.identity.domain import MIN_PASSWORD_LENGTH, Role, WeakPasswordError, validate_password
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository
from app.modules.identity.services import hash_password

identity_cli = AppGroup("identity", help="Identity administration.")


PASSWORD_POLICY = (
    f"Sifre kurallari: en az {MIN_PASSWORD_LENGTH} karakter; buyuk/kucuk harf, rakam, sembolden en az ikisi; "
    "kullanici adini icermemeli; yaygin bir sifre olmamali. (Yazarken ekranda gorunmez - bu normaldir.)"
)
MAX_PASSWORD_ATTEMPTS = 3


def _rules(exc: WeakPasswordError) -> str:
    details = exc.details if isinstance(exc.details, dict) else {}
    return ", ".join(details.get("rules", []))


def _prompt_password(username: str) -> str:
    """Interactive prompt that explains the policy and retries instead of crashing."""
    click.echo(PASSWORD_POLICY)
    for attempt in range(1, MAX_PASSWORD_ATTEMPTS + 1):
        password: str = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        try:
            validate_password(password, username=username)
            return password
        except WeakPasswordError as exc:
            click.secho(f"Sifre kurala uymuyor ({_rules(exc)}). Deneme {attempt}/{MAX_PASSWORD_ATTEMPTS}.", fg="yellow")
    raise click.ClickException("admin olusturulmadi: gecerli sifre girilmedi")


@identity_cli.command("create-admin")
@click.option("--username", required=True)
@click.option("--email", default=None)
@click.option(
    "--password-env",
    default="NEOTV_ADMIN_PASSWORD",
    show_default=True,
    help="Environment variable holding the password (otherwise prompted, never echoed).",
)
@click.option("--skip-existing", is_flag=True, help="Exit successfully if the user already exists (idempotent setup).")
def create_admin(username: str, email: str | None, password_env: str, skip_existing: bool) -> None:
    """Create an admin. Never modifies an existing account (no silent password resets)."""
    with resolve(UnitOfWorkFactory)() as uow:
        exists = UserRepository(uow.session).username_exists(username)
    if exists:
        if skip_existing:
            click.echo(f"admin '{username}' already exists - skipped")
            return
        raise click.ClickException(f"user '{username}' already exists — refusing to modify it")
    password = os.environ.get(password_env)
    if password:
        try:
            validate_password(password, username=username)
        except WeakPasswordError as exc:
            raise click.ClickException(f"${password_env} is too weak: {_rules(exc)}") from exc
    else:
        password = _prompt_password(username)
    with resolve(UnitOfWorkFactory)() as uow:
        users = UserRepository(uow.session)
        if users.username_exists(username):  # raced with another process
            raise click.ClickException(f"user '{username}' already exists — refusing to modify it")
        users.add(
            User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=Role.ADMIN,
                is_active=True,
                token_version=1,
                created_at=resolve(Clock).now(),
            )
        )
    click.echo(f"admin '{username}' created")


@identity_cli.command("promote")
@click.argument("username")
def promote(username: str) -> None:
    """Grant the admin role to an existing user."""
    with resolve(UnitOfWorkFactory)() as uow:
        user = UserRepository(uow.session).by_username(username)
        if user is None:
            raise click.ClickException(f"user '{username}' not found")
        user.role = Role.ADMIN
        user.token_version += 1
    click.echo(f"'{username}' is now an admin (existing tokens revoked)")
