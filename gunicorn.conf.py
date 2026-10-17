"""gunicorn settings that must live in Python (hooks). CLI flags in the Dockerfile/compose still apply.

Prometheus with several worker processes: each worker counts in its own memory, and a scrape lands
on one random worker — counters jump, latency histograms see a fraction of the traffic. In
multiprocess mode every worker writes its values to files in PROMETHEUS_MULTIPROC_DIR and the
scraped worker merges them (app.kernel.observability.metrics). This file sets that up:

* the directory is set here, in the master, before any worker imports prometheus_client;
* it is emptied when the master starts (a restarted container must not resume old counts);
* a worker that exits has its live gauges removed (``mark_process_dead``).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

multiproc_dir = os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", str(Path(tempfile.gettempdir()) / "neotv-prometheus"))


def on_starting(server: Any) -> None:
    shutil.rmtree(multiproc_dir, ignore_errors=True)
    Path(multiproc_dir).mkdir(parents=True, exist_ok=True)


def child_exit(server: Any, worker: Any) -> None:
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid, multiproc_dir)
