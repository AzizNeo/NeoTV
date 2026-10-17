"""Browser telemetry: Web Vitals and uncaught errors, sent by the SPA with ``sendBeacon``.

    POST /api/v1/kernel/client-events   {"events": [ … up to 20 … ]}   → 204

Our own endpoint (no third-party service, CSP untouched). Public — errors happen before sign-in
too — so it is shaped for hostile input:

* **Closed sets only reach metrics.** Vital names, ratings and error sources are enums; free text
  (messages, stacks, paths) only reaches a log line, never a label.
* **Secrets are stripped before logging.** Query strings and fragments (signed media URLs carry
  their signature there) and JWT-shaped tokens are removed from messages, stacks and paths.
* **Bounded.** ≤ 20 events per call, capped field lengths, per-IP rate limit.

An error event carries the browser's ``trace_id`` (``ApiError.traceId``): the log line joins the
API trace and log lines of the call that failed.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Literal

from flask import Blueprint, Response
from pydantic import BaseModel, ConfigDict, Field

from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.http.responses import no_content
from app.kernel.observability.metrics import Metrics
from app.kernel.resilience.rate_limit import Rate

blueprint = Blueprint("kernel", __name__)  # operation ids: kernel_<function>
_log = logging.getLogger("client")

_QUERY_OR_FRAGMENT = re.compile(r"[?#][^\s'\"()<>]*")
_JWT = re.compile(r"eyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}")


def scrub(text: str | None, limit: int) -> str | None:
    """Drops query strings, fragments and JWT-shaped tokens; then truncates."""
    if not text:
        return None
    return _JWT.sub("[jwt]", _QUERY_OR_FRAGMENT.sub("", text))[:limit]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VitalEvent(_Strict):
    kind: Literal["vital"]
    name: Literal["LCP", "INP", "CLS", "FCP", "TTFB"]
    value: float = Field(ge=0, le=600_000, description="Milliseconds; CLS is unitless")
    rating: Literal["good", "needs-improvement", "poor"]


class ErrorEvent(_Strict):
    kind: Literal["error"]
    source: Literal["error", "unhandledrejection", "render"]
    message: str = Field(max_length=1000)
    stack: str | None = Field(default=None, max_length=8000)
    path: str = Field(max_length=500, description="Page path (query and fragment are dropped)")
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    release: str | None = Field(default=None, max_length=40)


class ClientEvents(_Strict):
    events: list[Annotated[VitalEvent | ErrorEvent, Field(discriminator="kind")]] = Field(min_length=1, max_length=20)


@blueprint.post("/client-events")
@endpoint(
    auth="public",
    summary="Browser telemetry: Web Vitals and uncaught errors (sendBeacon; up to 20 per call)",
    tags=("kernel",),
    body=ClientEvents,
    status=204,
    rate=Rate("kernel.client_events", rps=1, burst=10, per="ip"),
)
def client_events(body: ClientEvents) -> Response:
    metrics = resolve(Metrics)
    for event in body.events:
        if isinstance(event, VitalEvent):
            if event.name == "CLS":
                metrics.web_vital_cls.observe(event.value)
            else:
                metrics.web_vital_seconds.labels(event.name).observe(event.value / 1000)
            metrics.web_vital_rating.labels(event.name, event.rating).inc()
        else:
            metrics.client_errors.labels(event.source).inc()
            _log.warning(
                "client.error %s",
                event.source,
                extra={
                    "client_source": event.source,
                    "client_message": scrub(event.message, 500),
                    "client_stack": scrub(event.stack, 4000),
                    "client_path": scrub(event.path, 300),
                    "client_trace_id": event.trace_id,
                    "client_release": event.release,
                },
            )
    return no_content()
