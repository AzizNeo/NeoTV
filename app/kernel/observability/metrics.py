"""Prometheus metrics (own registry — no global state shared with tests).

Under gunicorn with several workers, ``PROMETHEUS_MULTIPROC_DIR`` is set (gunicorn.conf.py) and
prometheus_client writes every worker's values to files there; ``render`` then merges all workers,
so a scrape sees the whole process group instead of one random worker. Gauges declare how they
merge (``multiprocess_mode``); in a single process (dev, tests, Celery) all of this is inert.
"""

from __future__ import annotations

import hmac
import os
import time
from collections.abc import Callable

from flask import Blueprint, Flask, Response, g, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_requests = Counter(
            "neotv_http_requests_total", "HTTP requests", ["endpoint", "method", "status"], registry=self.registry
        )
        self.http_latency = Histogram(
            "neotv_http_request_seconds",
            "HTTP request latency",
            ["endpoint"],
            registry=self.registry,
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        )
        self.playback_open = Counter(
            "neotv_playback_open_total", "Playback session open attempts", ["result"], registry=self.registry
        )
        # Global facts (read from the database at scrape time): the freshest reading of a live worker.
        self.outbox_lag = Gauge(
            "neotv_outbox_lag_seconds",
            "Age of the oldest pending outbox event",
            registry=self.registry,
            multiprocess_mode="livemostrecent",
        )
        self.dead_letters = Gauge(
            "neotv_outbox_dead_letters",
            "Unresolved dead letters",
            registry=self.registry,
            multiprocess_mode="livemostrecent",
        )
        # Viewer experience, from the player's one QoE report per session (trusted reports only; see
        # PlaybackSessionService.record_qoe). `device` is a closed set: tv, tablet, mobile, desktop, other.
        self.playback_startup = Histogram(
            "neotv_playback_startup_seconds",
            "Time from opening a stream to the first frame",
            ["device"],
            registry=self.registry,
            buckets=(0.25, 0.5, 1, 1.5, 2, 3, 5, 8, 13, 20, 30),
        )
        self.playback_watch = Counter(
            "neotv_playback_watch_seconds_total", "Seconds of video actually played", ["device"], registry=self.registry
        )
        self.playback_rebuffer = Counter(
            "neotv_playback_rebuffer_seconds_total",
            "Seconds spent stalled after start",
            ["device"],
            registry=self.registry,
        )
        self.playback_rebuffer_events = Counter(
            "neotv_playback_rebuffer_events_total", "Stalls after start", ["device"], registry=self.registry
        )
        # Origin failures behind the media proxy, by cause (closed set — never the URL or the host).
        self.proxy_errors = Counter(
            "neotv_playback_proxy_errors_total", "Media proxy upstream failures", ["reason"], registry=self.registry
        )
        self.active_streams = Gauge(
            "neotv_playback_active_streams",
            "Streams holding a concurrency slot right now (all accounts)",
            registry=self.registry,
            multiprocess_mode="livemostrecent",
        )
        # Per-process state (each worker has its own breakers): open if open in any live worker.
        self.circuit_open = Gauge(
            "neotv_circuit_open",
            "1 when a circuit is open",
            ["name"],
            registry=self.registry,
            multiprocess_mode="livemax",
        )
        self._collectors: list[Callable[[], None]] = []

    def add_collector(self, fn: Callable[[], None]) -> None:
        self._collectors.append(fn)

    def render(self) -> bytes:
        for collector in self._collectors:
            collector()
        directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
        if not directory:
            return generate_latest(self.registry)
        merged = CollectorRegistry()
        multiprocess.MultiProcessCollector(merged, path=directory)
        return generate_latest(merged)


def install_metrics(app: Flask, metrics: Metrics, *, token: str | None) -> None:
    @app.before_request
    def _start() -> None:
        g._metrics_t0 = time.perf_counter()

    @app.after_request
    def _observe(response: Response) -> Response:
        started = g.pop("_metrics_t0", None)
        endpoint = request.endpoint or "unmatched"
        if started is not None:
            metrics.http_latency.labels(endpoint).observe(time.perf_counter() - started)
        metrics.http_requests.labels(endpoint, request.method, str(response.status_code)).inc()
        return response

    blueprint = Blueprint("kernel_metrics", __name__)

    @blueprint.get("/metrics")
    def _metrics() -> Response:
        if token is not None:
            presented = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(presented, token):
                return Response("forbidden\n", status=403, mimetype="text/plain")
        elif request.remote_addr not in {"127.0.0.1", "::1"}:
            return Response("forbidden\n", status=403, mimetype="text/plain")
        return Response(metrics.render(), mimetype=CONTENT_TYPE_LATEST)

    app.register_blueprint(blueprint, url_prefix="/api/v1/kernel")
