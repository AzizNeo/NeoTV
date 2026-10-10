from __future__ import annotations

from typing import Any

from flask import Flask

from app.modules.notifications.services import EmailDeliveryService, TemplateCatalog


def validate(container: Any, _app: Flask) -> None:
    """Fail at startup — not on the first mail — when EMAIL_BACKEND names no
    transport or two modules contribute the same template key."""
    container.resolve(TemplateCatalog).keys()
    container.resolve(EmailDeliveryService).transport_name()
