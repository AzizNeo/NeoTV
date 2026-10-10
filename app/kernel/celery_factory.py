"""The ONE Celery application (ASY-01).

Web, worker and beat all import ``app.wsgi:celery`` — same factory, same
configuration, same task registry. Task modules, beat entries and routes are
collected from module manifests; a manifest that lists a task module which
does not exist is a named boot error, not a worker crash at 3 a.m.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from typing import Any

from celery import Celery, Task
from flask import Flask

from app.kernel.errors import DuplicateScheduleError, ModuleContractError
from app.kernel.manifest import ModuleManifest
from app.kernel.outbox.tasks import KERNEL_BEAT_SCHEDULE
from app.kernel.outbox.trigger import dispatch_if_pending
from app.kernel.settings import Settings

KERNEL_TASK_MODULES = ("app.kernel.outbox.tasks",)
KERNEL_TASK_ROUTES = {"kernel.outbox.*": {"queue": "outbox"}}


def create_celery(app: Flask, manifests: Sequence[ModuleManifest], settings: Settings) -> Celery:
    celery = Celery(app.import_name)

    class FlaskTask(Task):
        abstract = True

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            with app.app_context():
                result = self.run(*args, **kwargs)
                if not self.name.startswith("kernel.outbox."):  # deliver dispatches its own follow-ups
                    dispatch_if_pending(op="outbox.dispatch_after_task")
                return result

    celery.Task = FlaskTask

    includes: list[str] = list(KERNEL_TASK_MODULES)
    beat: dict[str, dict[str, Any]] = dict(KERNEL_BEAT_SCHEDULE)
    routes: dict[str, dict[str, str]] = dict(KERNEL_TASK_ROUTES)
    for manifest in manifests:
        for module_path in manifest.task_modules:
            if importlib.util.find_spec(module_path) is None:
                raise ModuleContractError(manifest.name, f"task module not found: {module_path}")
            includes.append(module_path)
        for name, entry in manifest.beat_schedule.items():
            if name in beat:
                raise DuplicateScheduleError(name, owner=manifest.name)
            beat[name] = entry
        for pattern, route in manifest.task_routes.items():
            if pattern in routes:
                raise DuplicateScheduleError(f"route:{pattern}", owner=manifest.name)
            routes[pattern] = route

    celery.conf.update(
        broker_url=settings.celery_broker_url,
        result_backend=settings.celery_result_backend or settings.celery_broker_url,
        include=includes,
        imports=includes,
        beat_schedule=beat,
        beat_scheduler="redbeat.RedBeatScheduler",
        redbeat_redis_url=settings.celery_broker_url,
        redbeat_lock_timeout=90,
        task_routes=routes,
        task_default_queue="default",
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_max_tasks_per_child=500,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=3600,
        task_track_started=True,
        task_store_eager_result=True,  # eager (dev/test) results are visible through /api/v1/tasks too
        broker_connection_retry_on_startup=True,
        task_always_eager=settings.celery_always_eager,
        task_eager_propagates=False,
        timezone="UTC",
        enable_utc=True,
    )
    celery.set_default()
    for module_path in includes:  # register every task now (web process included)
        importlib.import_module(module_path)
    app.extensions["celery"] = celery
    return celery
