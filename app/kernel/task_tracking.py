"""Background task tracking for HTTP clients (202 Accepted + polling).

Enqueueing through :class:`TaskTracker` records the task owner; the status
endpoint only reveals a task to the principal that started it (no task-id
enumeration across users).
"""

from __future__ import annotations

from typing import Any

from celery.result import AsyncResult
from flask import Blueprint, current_app
from pydantic import BaseModel

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.errors import ApiError
from app.kernel.security.auth import current_user

OWNER_TTL = 24 * 3600


class TaskStatus(BaseModel):
    task_id: str
    state: str
    progress: int
    message: str | None = None
    result: Any = None
    error: str | None = None


class TaskTracker:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def enqueue(
        self, task: Any, *, owner_id: int, args: tuple[Any, ...] = (), kwargs: dict[str, Any] | None = None
    ) -> str:
        result = task.apply_async(args=args, kwargs=kwargs or {})
        self._redis.set(f"task:owner:{result.id}", str(owner_id), ex=OWNER_TTL)
        return str(result.id)

    def owner(self, task_id: str) -> int | None:
        raw = self._redis.get(f"task:owner:{task_id}")
        return int(raw) if raw else None


blueprint = Blueprint("kernel_tasks", __name__)


@blueprint.get("/<task_id>")
@endpoint(summary="Status of a background task started by the current user", response=TaskStatus)
def task_status(task_id: str) -> TaskStatus:
    if resolve(TaskTracker).owner(task_id) != current_user.id:
        raise ApiError("TASK_NOT_FOUND", 404, "Task not found")
    result = AsyncResult(task_id, app=current_app.extensions["celery"])
    state = result.state
    info = result.info if isinstance(result.info, dict) else {}
    if state == "SUCCESS":
        return TaskStatus(task_id=task_id, state=state, progress=100, result=result.result)
    if state == "FAILURE":
        return TaskStatus(task_id=task_id, state=state, progress=100, error=type(result.result).__name__)
    return TaskStatus(
        task_id=task_id,
        state=state,
        progress=int(info.get("progress", 0)),
        message=info.get("message"),
    )
