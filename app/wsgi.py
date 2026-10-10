"""Process entry point shared by every runtime.

    waitress-serve --call app.wsgi:get_app      (or: python run.py)
    gunicorn 'app.wsgi:app'
    celery -A app.wsgi:celery worker / beat

Web, worker and beat therefore always run the *same* factory with the *same*
settings, manifests and task registry (ASY-01).
"""

from __future__ import annotations

from celery import Celery
from flask import Flask

from app import create_app

app: Flask = create_app()
celery: Celery = app.extensions["celery"]


def get_app() -> Flask:
    return app
