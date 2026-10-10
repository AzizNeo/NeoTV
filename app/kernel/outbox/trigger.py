"""Low-latency outbox dispatch.

The beat schedule dispatches every few seconds as a safety net. To keep the
typical latency near zero, the kernel also triggers a dispatch right after a
request (or Celery task) that committed outbox events.
"""

from __future__ import annotations

import logging

from flask import Flask, Response

from app.kernel.db import db
from app.kernel.outbox.repository import PENDING_FLAG
from app.kernel.resilience.best_effort import best_effort

_log = logging.getLogger("kernel.outbox.trigger")


def _schedule_dispatch() -> None:
    from app.kernel.outbox.tasks import dispatch_outbox

    dispatch_outbox.apply_async()


def dispatch_if_pending(*, op: str) -> None:
    """Call inside the app context whose session committed outbox rows.

    Must run *in* that context: Flask-SQLAlchemy scopes sessions per app
    context, so a Celery ``task_postrun`` signal (fired after the task's
    context is gone) would look at a different, empty session — which is why
    the Celery integration calls this from ``FlaskTask.__call__`` instead.
    """
    try:
        pending = db.session.info.pop(PENDING_FLAG, False)
    except RuntimeError:  # no app context
        return
    if pending:
        best_effort(_schedule_dispatch, op=op)


def install(app: Flask) -> None:
    @app.after_request
    def _dispatch_after_request(response: Response) -> Response:
        if response.status_code < 500:
            dispatch_if_pending(op="outbox.dispatch_after_request")
        else:
            db.session.info.pop(PENDING_FLAG, None)
        return response
