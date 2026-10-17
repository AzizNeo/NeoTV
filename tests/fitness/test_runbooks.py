"""Every alert links to a runbook section that exists — and every section belongs to an alert.

An alert whose runbook link leads nowhere is found at the worst moment: by someone paged at
night. This keeps deploy/prometheus/neotv.rules.yml and docs/runbooks.md in step.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "deploy/prometheus/neotv.rules.yml"
RUNBOOKS = ROOT / "docs/runbooks.md"


def _alerts() -> list[dict]:
    groups = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]
    return [rule for group in groups for rule in group["rules"] if "alert" in rule]


def _anchors() -> set[str]:
    return set(re.findall(r'<a id="([a-z0-9-]+)"></a>', RUNBOOKS.read_text(encoding="utf-8")))


def test_every_alert_has_a_severity_and_a_runbook_that_exists():
    anchors = _anchors()
    for alert in _alerts():
        assert alert["labels"]["severity"] in {"page", "ticket"}, alert["alert"]
        url = alert["annotations"].get("runbook_url", "")
        assert url.startswith("docs/runbooks.md#"), alert["alert"]
        assert url.split("#", 1)[1] in anchors, f"{alert['alert']}: no section {url}"


def test_every_runbook_section_belongs_to_an_alert():
    linked = {a["annotations"]["runbook_url"].split("#", 1)[1] for a in _alerts()}
    assert _anchors() - linked == set(), "runbook sections no alert links to"
