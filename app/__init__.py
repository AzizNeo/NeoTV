"""Composition root.

``create_app`` wires the kernel, validates and boots the installed modules
(puzzle pieces) through the module registry, and creates the single Celery
application. Nothing in here knows about any specific module.
"""

from __future__ import annotations

from flask import Flask

from app.kernel.settings import PROJECT_ROOT, Settings, get_settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or get_settings()

    from app.kernel.bootstrap import install_kernel, register_kernel_services
    from app.kernel.celery_factory import create_celery
    from app.kernel.cli import kernel_cli
    from app.kernel.container import Container
    from app.kernel.db import db, migrate
    from app.kernel.events.bus import EventBus
    from app.kernel.extensions import ExtensionRegistry
    from app.kernel.http.errors import ErrorMap
    from app.kernel.registry import ModuleRegistry, load_manifests
    from app.kernel.security.permissions import PermissionCatalog
    from app.modules import INSTALLED_MODULES

    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(settings.flask_config())

    db.init_app(app)
    migrate.init_app(app, db, directory=str(PROJECT_ROOT / "migrations"))

    container = Container()
    app.extensions["container"] = container
    register_kernel_services(container, settings)
    install_kernel(app, container, settings)

    registry = ModuleRegistry(load_manifests(INSTALLED_MODULES), disabled=settings.disabled)
    order = registry.resolve_order()
    with app.app_context():
        registry.boot(
            app,
            container,
            bus=container.resolve(EventBus),
            error_map=container.resolve(ErrorMap),
            extensions=container.resolve(ExtensionRegistry),
            permissions=container.resolve(PermissionCatalog),
        )
    app.extensions["module_registry"] = registry
    create_celery(app, order, settings)
    app.cli.add_command(kernel_cli)

    @app.teardown_appcontext
    def _drop_request_scope(_exc: BaseException | None) -> None:
        from flask import g

        g.pop("_di_request_scope", None)

    return app
