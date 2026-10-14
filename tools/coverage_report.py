"""Coverage per module — the unit this codebase is built from — with floors that only go up.

    pytest --cov --cov-report=json
    python -m tools.coverage_report coverage.json [--summary FILE] [--badge FILE]

* Groups coverage.py's JSON report by module (``app/modules/<name>``, ``app/kernel``, …) and
  prints a table (Markdown with ``--summary``: CI appends it to the job summary page).
* Enforces ``[tool.neotv.coverage]`` from pyproject.toml: a ``total`` floor and one floor per
  module. A module below its floor fails the build *by name*; a module far above its floor is
  reported as "raise the floor" (the ratchet: coverage may grow, never quietly shrink).
* ``--badge`` writes a shields.io endpoint JSON (the README badge reads it).

Coverage counts statements and branches together, like coverage.py's own percentage.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATCHET_SLACK = 3.0  # points above the floor before we suggest raising it


@dataclass
class Area:
    name: str
    covered: int = 0
    total: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.covered / self.total if self.total else 100.0


def area_of(path: str) -> str:
    parts = Path(path).as_posix().split("/")
    if len(parts) > 3 and parts[1] == "modules":
        return parts[2]  # app/modules/<name>/…
    if len(parts) > 2 and parts[1] != "modules":
        return parts[1]  # app/kernel/…, app/shared_kernel/…
    return "app"  # the package's own files (app/__init__.py, app/wsgi.py, app/modules/__init__.py)


def aggregate(report: dict) -> tuple[Area, dict[str, Area]]:
    areas: dict[str, Area] = defaultdict(lambda: Area(""))
    for path, data in report["files"].items():
        s = data["summary"]
        area = areas[area_of(path)]
        area.covered += s["covered_lines"] + s.get("covered_branches", 0)
        area.total += s["num_statements"] + s.get("num_branches", 0)
    for name, area in areas.items():
        area.name = name
    t = report["totals"]
    total = Area(
        "total", t["covered_lines"] + t.get("covered_branches", 0), t["num_statements"] + t.get("num_branches", 0)
    )
    return total, dict(areas)


def badge(percent: float) -> dict[str, object]:
    color = "brightgreen" if percent >= 90 else "green" if percent >= 80 else "yellow" if percent >= 70 else "orange"
    return {"schemaVersion": 1, "label": "backend coverage", "message": f"{percent:.0f}%", "color": color}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--summary", type=Path, help="append a Markdown table here (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--badge", type=Path, help="write a shields.io endpoint JSON here")
    args = parser.parse_args(argv)

    floors = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["neotv"]["coverage"]
    module_floors: dict[str, float] = floors.get("modules", {})
    total, areas = aggregate(json.loads(args.report.read_text(encoding="utf-8")))

    failures: list[str] = []
    advice: list[str] = []
    rows = []
    for area in sorted(areas.values(), key=lambda a: a.percent):
        floor = module_floors.get(area.name)
        status = "—"
        if floor is not None:
            if area.percent < floor:
                status = "❌ below floor"
                failures.append(f"{area.name}: {area.percent:.1f}% < floor {floor}%")
            elif area.percent >= floor + RATCHET_SLACK:
                status = "⬆ raise floor"
                advice.append(f"{area.name}: {area.percent:.1f}% — floor {floor}% can go up")
            else:
                status = "✅"
        rows.append((area.name, area.percent, floor, area.total, status))
    unfloored = sorted(name for name in areas if name not in module_floors and name != "app")
    if unfloored:
        failures.append(f"no floor configured for: {', '.join(unfloored)} (add them to [tool.neotv.coverage.modules])")
    if total.percent < floors["total"]:
        failures.append(f"total: {total.percent:.1f}% < floor {floors['total']}%")

    lines = [
        f"### Backend coverage: {total.percent:.1f}% (floor {floors['total']}%)",
        "",
        "| Area | Coverage | Floor | Statements + branches | |",
        "| --- | ---: | ---: | ---: | --- |",
        *(f"| `{n}` | {p:.1f}% | {'' if f is None else f'{f}%'} | {s} | {st} |" for n, p, f, s, st in rows),
    ]
    if advice:
        lines += ["", "Ratchet — these floors can be raised:", *(f"- {a}" for a in advice)]
    text = "\n".join(lines)
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if args.badge:
        args.badge.parent.mkdir(parents=True, exist_ok=True)
        args.badge.write_text(json.dumps(badge(total.percent)), encoding="utf-8")

    for failure in failures:
        print(f"::error title=Coverage::{failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
