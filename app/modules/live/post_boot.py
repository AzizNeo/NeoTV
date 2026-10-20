"""live's boot hook: publish the catch-up archive's state as metrics (ADR-0012).

Read from the archive volume and the database at scrape time, like playback's active streams:
the API mounts the volume, so whichever process is scraped reports the same truth. The channel
label is a live channel id — a short, operator-curated list, never a viewer.
"""

from __future__ import annotations

from typing import Any

from app.kernel.observability.metrics import Metrics
from app.kernel.resilience.best_effort import best_effort
from app.modules.live.archive import ArchiveStorage
from app.modules.live.services import ArchiveService


def install_metrics(container: Any, app: Any) -> None:
    metrics = container.resolve(Metrics)

    def collect() -> None:
        metrics.archive_disk_used.set(container.resolve(ArchiveStorage).usage().ratio)
        lags = container.resolve(ArchiveService).lag_seconds()
        metrics.archive_lag.clear()  # a channel switched off must not keep reporting its last value
        for channel_id, lag in lags.items():
            metrics.archive_lag.labels(str(channel_id)).set(lag)

    metrics.add_collector(lambda: best_effort(collect, op="metrics.archive"))
