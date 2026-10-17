"""The Grafana dashboard only queries what exists.

A renamed metric or recording rule does not break a dashboard loudly — its charts just go empty.
This test reads every query in deploy/grafana/neotv-overview.json and checks each NeoTV series it
names against the metrics the app registers and the rules Prometheus records. (Query *syntax* is
checked in CI by promtool: generate_dashboard.py --as-rules.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from app.kernel.observability.metrics import Metrics

ROOT = Path(__file__).resolve().parents[2]
BOARD = json.loads((ROOT / "deploy/grafana/neotv-overview.json").read_text(encoding="utf-8"))
RULES = yaml.safe_load((ROOT / "deploy/prometheus/neotv.rules.yml").read_text(encoding="utf-8"))
SUFFIXES = {"counter": ("_total",), "histogram": ("_bucket", "_sum", "_count"), "gauge": ("",)}


def _known_series() -> set[str]:
    known: set[str] = set()
    for family in Metrics().registry.collect():
        known |= {family.name + suffix for suffix in SUFFIXES.get(family.type, ("",))}
    for group in RULES["groups"]:
        known |= {rule["record"] for rule in group["rules"] if "record" in rule}
    return known


def _targets() -> list[tuple[str, str]]:
    return [(p["title"], t["expr"]) for p in BOARD["panels"] for t in p.get("targets", [])]


def test_every_query_names_only_series_that_exist():
    known = _known_series()
    for title, expr in _targets():
        named = set(re.findall(r"\bneotv[_:][a-z0-9_:]+", expr))
        assert named, f"{title}: queries no NeoTV series"
        assert named <= known, f"{title}: unknown {sorted(named - known)}"


def test_every_metric_the_app_exports_is_on_the_dashboard():
    """A metric nobody looks at is a metric nobody maintains: each family appears somewhere."""
    used = " ".join(expr for _, expr in _targets())
    rules = json.dumps(RULES)
    for family in Metrics().registry.collect():
        assert family.name in used or family.name in rules, f"{family.name} is on no panel"


def test_panels_are_sound():
    ids = [p["id"] for p in BOARD["panels"]]
    assert len(ids) == len(set(ids))
    for panel in BOARD["panels"]:
        pos = panel["gridPos"]
        assert pos["x"] + pos["w"] <= 24, panel["title"]
        if panel["type"] != "row":
            assert panel["datasource"]["uid"] == "${datasource}", panel["title"]  # no hard-wired source
    assert BOARD["uid"] == "neotv-overview"  # stable: links and provisioning refer to it
