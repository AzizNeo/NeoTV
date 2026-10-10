"""Alembic environment (driven by Flask-Migrate inside the app factory).

* Metadata = every installed module's models (imported by ``create_app``).
* ``UTCDateTime`` is rendered as ``sa.DateTime(timezone=True)`` so generated
  revisions never import application code (revisions are immutable history).
* Empty autogenerate runs produce no file.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig
from typing import Any

from alembic import context
from flask import current_app

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
logger = logging.getLogger("alembic.env")


def _engine() -> Any:
    return current_app.extensions["migrate"].db.engine


def _metadata() -> Any:
    return current_app.extensions["migrate"].db.metadata


def _render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    from app.kernel.db import UTCDateTime

    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _process_revision_directives(ctx: Any, revision: Any, directives: list[Any]) -> None:
    if getattr(config.cmd_opts, "autogenerate", False) and directives and directives[0].upgrade_ops.is_empty():
        directives[:] = []
        logger.info("No changes in schema detected.")


config.set_main_option("sqlalchemy.url", _engine().url.render_as_string(hide_password=False).replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=_metadata(),
        literal_binds=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    conf_args = dict(current_app.extensions["migrate"].configure_args)
    conf_args.setdefault("process_revision_directives", _process_revision_directives)
    conf_args.setdefault("render_item", _render_item)
    with _engine().connect() as connection:
        context.configure(connection=connection, target_metadata=_metadata(), **conf_args)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
