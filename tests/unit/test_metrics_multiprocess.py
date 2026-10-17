"""Metrics under gunicorn: several worker processes, one scrape that must see all of them.

Every process here is a real subprocess — the workers, the scrape and the gunicorn hooks. That is
not only realism: prometheus_client picks its storage when it is first imported, so importing it
in the pytest process with PROMETHEUS_MULTIPROC_DIR set would switch the whole test session to
multiprocess storage and break unrelated tests.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _worker(directory: Path, body: str) -> str:
    code = "from app.kernel.observability.metrics import Metrics\nm = Metrics()\n" + textwrap.dedent(body)
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(directory)}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return done.stdout


def _hook(directory: Path, call: str) -> None:
    """Runs a gunicorn.conf.py hook in its own process, as the gunicorn master would."""
    code = f"import runpy, types\nconf = runpy.run_path('gunicorn.conf.py')\n{call}"
    env = {**os.environ, "PROMETHEUS_MULTIPROC_DIR": str(directory)}
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)


def _value(scrape: str, sample: str) -> float:
    match = re.search(rf"^{re.escape(sample)} (\S+)$", scrape, flags=re.M)
    assert match, f"{sample} not in scrape:\n{scrape}"
    return float(match[1])


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return tmp_path


def test_a_scrape_sums_every_worker(directory):
    _worker(
        directory, 'm.http_requests.labels("home", "GET", "200").inc(3)\nm.http_latency.labels("home").observe(0.2)'
    )
    _worker(
        directory, 'm.http_requests.labels("home", "GET", "200").inc(2)\nm.http_latency.labels("home").observe(0.4)'
    )
    scrape = _worker(directory, "print(m.render().decode())")
    assert _value(scrape, 'neotv_http_requests_total{endpoint="home",method="GET",status="200"}') == 5
    assert _value(scrape, 'neotv_http_request_seconds_count{endpoint="home"}') == 2


def test_an_open_circuit_in_any_live_worker_is_open_and_a_dead_worker_is_forgotten(directory):
    pid = int(_worker(directory, 'import os\nm.circuit_open.labels("tmdb").set(1)\nprint(os.getpid())'))
    _worker(directory, 'm.circuit_open.labels("tmdb").set(0)')
    assert _value(_worker(directory, "print(m.render().decode())"), 'neotv_circuit_open{name="tmdb"}') == 1

    # gunicorn calls child_exit when a worker dies: its live gauges must not linger.
    _hook(directory, f"conf['child_exit'](None, types.SimpleNamespace(pid={pid}))")
    assert _value(_worker(directory, "print(m.render().decode())"), 'neotv_circuit_open{name="tmdb"}') == 0


def test_the_master_starts_from_empty_counters(directory):
    _worker(directory, 'm.http_requests.labels("home", "GET", "200").inc(7)')
    assert any(directory.iterdir())
    _hook(directory, "conf['on_starting'](None)")  # a restarted container must not resume old counts
    assert not any(directory.iterdir())
    assert "neotv_http_requests_total{" not in _worker(directory, "print(m.render().decode())")


def test_single_process_mode_is_unchanged():
    code = (
        "from app.kernel.observability.metrics import Metrics\nm = Metrics()\n"
        "m.http_requests.labels('home', 'GET', '200').inc()\nprint(m.render().decode())"
    )
    env = {k: v for k, v in os.environ.items() if k != "PROMETHEUS_MULTIPROC_DIR"}
    scrape = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert _value(scrape.stdout, 'neotv_http_requests_total{endpoint="home",method="GET",status="200"}') == 1


def test_this_test_module_left_the_session_in_single_process_mode():
    assert "PROMETHEUS_MULTIPROC_DIR" not in os.environ
