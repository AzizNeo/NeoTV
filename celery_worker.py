"""Backward-compatible Celery entry point: ``celery -A celery_worker.celery worker``.

Prefer ``celery -A app.wsgi:celery ...`` (same object)."""

from __future__ import annotations

from app.wsgi import celery

__all__ = ["celery"]
