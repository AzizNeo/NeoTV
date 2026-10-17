"""Writes neotv-overview.json — the NeoTV Grafana dashboard (import it, pick the Prometheus source).

    python deploy/grafana/generate_dashboard.py                 # write
    python deploy/grafana/generate_dashboard.py --check         # CI: fail if the JSON is stale
    python deploy/grafana/generate_dashboard.py --as-rules F    # every query as a rule file, for
                                                                #   `promtool check rules F` (syntax)
A hand-written dashboard is thousands of lines of JSON nobody reviews; this is the reviewable
source. tests/fitness/test_dashboard.py checks that every query uses metrics that exist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).with_name("neotv-overview.json")
DS = {"type": "prometheus", "uid": "${datasource}"}
API = 'endpoint!~"kernel_health\\\\..*|kernel_metrics\\\\..*|kernel\\\\.client_events|playback\\\\.proxy"'

# SLO stat tiles: (title, recording-rule prefix, objective)
SLOS = (
    ("API availability", "availability", 0.995),
    ("API latency ≤ 1 s", "latency", 0.99),
    ("Playback start ≤ 3 s", "playback_start", 0.95),
)


def _ts(title: str, targets: list[tuple[str, str]], unit: str = "short", desc: str = "") -> dict:
    return {
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": DS,
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        "targets": [
            {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": chr(65 + i)}
            for i, (expr, legend) in enumerate(targets)
        ],
    }


def _stat(title: str, expr: str, unit: str, steps: list[tuple[str, float | None]], desc: str = "") -> dict:
    return {
        "type": "stat",
        "title": title,
        "description": desc,
        "datasource": DS,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": 2,
                "thresholds": {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]},
            },
            "overrides": [],
        },
        "options": {"colorMode": "background", "graphMode": "area", "reduceOptions": {"calcs": ["lastNotNull"]}},
        "targets": [{"datasource": DS, "expr": expr, "refId": "A"}],
    }


def _row(title: str) -> dict:
    return {"type": "row", "title": title, "collapsed": False, "panels": []}


def panels() -> list[dict]:
    out: list[dict] = [_row("Service level objectives — 30-day error budget left")]
    for title, sli, objective in SLOS:
        budget = round(1 - objective, 6)
        out.append(
            _stat(
                f"{title} — budget left",
                f"1 - avg_over_time(neotv:sli_{sli}_errors:ratio_rate5m[30d]) / {budget}",
                "percentunit",
                [("red", None), ("orange", 0.25), ("green", 0.5)],
                f"Objective {objective:.1%}. 100 % = no bad events this month; 0 % = budget spent "
                "(reliability work before features). Runbook: docs/runbooks.md",
            )
        )
    out += [
        _ts(
            "Error budget burn rate (1 h) — 14.4 pages, 6 opens a ticket",
            [(f"neotv:sli_{sli}_errors:ratio_rate1h / {round(1 - o, 6)}", title) for title, sli, o in SLOS],
        ),
        _row("API"),
        _ts(
            "Requests by status class",
            # One query per class (no label_replace: its "${1}" would collide with Grafana variables).
            [(f'sum(rate(neotv_http_requests_total{{status=~"{c}..",{API}}}[5m]))', f"{c}xx") for c in "2345"],
            "reqps",
        ),
        _ts(
            "Latency",
            [
                (
                    f"histogram_quantile({q}, sum by (le) (rate(neotv_http_request_seconds_bucket{{{API}}}[5m])))",
                    f"p{int(q * 100)}",
                )
                for q in (0.5, 0.95, 0.99)
            ],
            "s",
        ),
        _ts(
            "Server errors by endpoint (top 5)",
            [
                (
                    f'topk(5, sum by (endpoint) (rate(neotv_http_requests_total{{status=~"5..",{API}}}[5m])))',
                    "{{endpoint}}",
                )
            ],
            "reqps",
        ),
        _row("Playback"),
        _ts("Active streams", [("max(neotv_playback_active_streams)", "streams")]),
        _ts(
            "Stream opens by result",
            [("sum by (result) (rate(neotv_playback_open_total[5m]))", "{{result}}")],
            "reqps",
            "ok, denied (rights / kids policy), limit (plan's simultaneous streams), error",
        ),
        _ts(
            "Time to first frame (p95) by device",
            [
                (
                    "histogram_quantile(0.95, sum by (device, le) (rate(neotv_playback_startup_seconds_bucket[15m])))",
                    "{{device}}",
                )
            ],
            "s",
        ),
        _ts(
            "Rebuffering ratio by device",
            [
                (
                    "sum by (device) (rate(neotv_playback_rebuffer_seconds_total[15m]))"
                    " / (sum by (device) (rate(neotv_playback_watch_seconds_total[15m]))"
                    " + sum by (device) (rate(neotv_playback_rebuffer_seconds_total[15m])))",
                    "{{device}}",
                )
            ],
            "percentunit",
            "Share of viewing time spent stalled",
        ),
        _ts(
            "Stalls per hour of viewing, by device",
            [
                (
                    "sum by (device) (rate(neotv_playback_rebuffer_events_total[15m])) * 3600"
                    " / sum by (device) (rate(neotv_playback_watch_seconds_total[15m]))",
                    "{{device}}",
                )
            ],
            "short",
            "How often playback stops (the ratio above says for how long): many short stalls hurt too",
        ),
        _ts(
            "Origin failures behind the media proxy, by cause",
            [("sum by (reason) (rate(neotv_playback_proxy_errors_total[5m]))", "{{reason}}")],
            "reqps",
        ),
        _row("Platform"),
        _ts("Outbox lag", [("max(neotv_outbox_lag_seconds)", "oldest undelivered event")], "s"),
        _ts("Dead letters waiting for a human", [("max(neotv_outbox_dead_letters)", "dead letters")]),
        _ts("Open circuits", [("max by (name) (neotv_circuit_open)", "{{name}}")]),
        _row("Browsers"),
        _ts(
            "Web Vitals (p75, as Google rates them)",
            [
                (f'histogram_quantile(0.75, sum by (le) (rate(neotv_web_vital_seconds_bucket{{name="{n}"}}[1h])))', n)
                for n in ("LCP", "INP", "FCP", "TTFB")
            ],
            "s",
        ),
        _ts(
            "Cumulative Layout Shift (p75)",
            [("histogram_quantile(0.75, sum by (le) (rate(neotv_web_vital_cls_bucket[1h])))", "CLS")],
        ),
        _ts(
            "Share of 'poor' ratings",
            [
                (
                    'sum by (name) (rate(neotv_web_vital_rating_total{rating="poor"}[1h]))'
                    " / sum by (name) (rate(neotv_web_vital_rating_total[1h]))",
                    "{{name}}",
                )
            ],
            "percentunit",
        ),
        _ts(
            "Uncaught errors in browsers",
            [("sum by (source) (rate(neotv_client_errors_total[5m])) * 60", "{{source}}")],
            "short",
            "Per minute",
        ),
    ]
    return out


def _layout(items: list[dict]) -> list[dict]:
    """Rows span the width; three stat tiles or two charts per line."""
    x = y = 0
    line_height = 0
    for panel_id, panel in enumerate(items, start=1):
        panel["id"] = panel_id
        width, height = {"row": (24, 1), "stat": (8, 5)}.get(panel["type"], (12, 8))
        if x + width > 24 or panel["type"] == "row":
            y, x, line_height = y + line_height, 0, 0
        panel["gridPos"] = {"x": x, "y": y, "w": width, "h": height}
        x, line_height = x + width, max(line_height, height)
        if panel["type"] == "row":
            y, x, line_height = y + height, 0, 0
    return items


def dashboard() -> dict:
    return {
        "uid": "neotv-overview",
        "title": "NeoTV — overview",
        "tags": ["neotv"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "1m",
        "time": {"from": "now-6h", "to": "now"},
        "templating": {
            "list": [{"name": "datasource", "type": "datasource", "query": "prometheus", "label": "Prometheus"}]
        },
        "annotations": {"list": []},
        "links": [],
        "panels": _layout(panels()),
    }


def queries(board: dict) -> list[str]:
    return [t["expr"] for p in board["panels"] for t in p.get("targets", [])]


def main(argv: list[str]) -> int:
    content = json.dumps(dashboard(), indent=2, ensure_ascii=False) + "\n"
    if "--as-rules" in argv:
        target = Path(argv[argv.index("--as-rules") + 1])
        rules = [{"record": f"dashboard:q{i}", "expr": e} for i, e in enumerate(queries(json.loads(content)))]
        target.write_text(json.dumps({"groups": [{"name": "dashboard-queries", "rules": rules}]}, indent=2))
        print(f"wrote {len(rules)} queries to {target}")
        return 0
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != content:
            print(f"{OUT.name} is stale: run python deploy/grafana/generate_dashboard.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
