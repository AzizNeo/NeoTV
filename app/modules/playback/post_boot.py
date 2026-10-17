"""playback's boot hook: publish the number of active streams as a metric.

The count lives in Redis (the concurrency slots), so any worker reads the global truth at scrape
time. Kept in the module: the kernel defines the metric, the module that owns the data feeds it.
"""

from __future__ import annotations

from typing import Any

from app.kernel.observability.metrics import Metrics
from app.kernel.resilience.best_effort import best_effort
from app.modules.playback.concurrency import StreamConcurrencyGuard


def install_metrics(container: Any, app: Any) -> None:
    metrics = container.resolve(Metrics)
    guard = container.resolve(StreamConcurrencyGuard)
    metrics.add_collector(
        lambda: best_effort(lambda: metrics.active_streams.set(guard.total_active()), op="metrics.active_streams")
    )
