"""Turn a k6 summary export into a Markdown report (CI step summary).

    k6 run --summary-export "$RUNNER_TEMP/k6.json" … deploy/load/neotv.js
    python3 tools/k6_summary.py "$RUNNER_TEMP/k6.json" >> "$GITHUB_STEP_SUMMARY"

Only ``metrics`` is read. The export also holds ``setup_data`` — the load accounts' access
tokens — so the raw file is never uploaded or printed; this report is what leaves the runner.
Standard library only (runs on a bare CI runner).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ENDPOINT = re.compile(r"^http_req_duration\{name:(?P<name>[\w.]+)\}$")


def _ms(value: float | None) -> str:
    return "–" if value is None else f"{value:,.0f} ms" if value >= 10 else f"{value:.1f} ms"


def report(summary: dict) -> str:
    metrics: dict[str, dict] = summary["metrics"]
    lines = ["## Load test (k6)", ""]

    lines += ["| Threshold | Value | Result |", "| --- | --- | --- |"]
    for name, metric in sorted(metrics.items()):
        for expression, crossed in metric.get("thresholds", {}).items():
            if expression == "max>=0":  # the per-endpoint reporting trick, not a real threshold
                continue
            value = metric.get("value", metric.get("count"))
            if expression.startswith("p("):
                value = _ms(metric.get(expression.split("<")[0]))
            elif expression.startswith("rate"):
                value = f"{float(value or 0):.2%}"
            lines.append(f"| `{name}` `{expression}` | {value} | {'❌ failed' if crossed else '✅'} |")

    lines += ["", "| Endpoint | Requests | median | p95 | p99 | max |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, metric in sorted(metrics.items()):
        if match := _ENDPOINT.match(name):
            lines.append(
                f"| `{match['name']}` | {metric.get('count', 0):,} | {_ms(metric.get('med'))} | "
                f"{_ms(metric.get('p(95)'))} | {_ms(metric.get('p(99)'))} | {_ms(metric.get('max'))} |"
            )

    reqs, iterations = metrics.get("http_reqs", {}), metrics.get("iterations", {})
    lines += [
        "",
        f"{reqs.get('count', 0):,} requests ({reqs.get('rate', 0):.1f}/s), "
        f"{iterations.get('count', 0):,} viewer sessions, peak {metrics.get('vus_max', {}).get('max', 0)} virtual users.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        raise SystemExit("usage: k6_summary.py <summary-export.json>")
    sys.stdout.write(report(json.loads(Path(argv[0]).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
