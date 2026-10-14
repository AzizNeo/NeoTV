"""tools/coverage_report: per-module coverage with floors that fail the build by name."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.coverage_report import aggregate, area_of, main


def _file(covered: int, statements: int) -> dict:
    return {
        "summary": {"covered_lines": covered, "num_statements": statements, "covered_branches": 0, "num_branches": 0}
    }


def _report(files: dict[str, dict]) -> dict:
    covered = sum(f["summary"]["covered_lines"] for f in files.values())
    total = sum(f["summary"]["num_statements"] for f in files.values())
    return {
        "files": files,
        "totals": {"covered_lines": covered, "num_statements": total, "covered_branches": 0, "num_branches": 0},
    }


def test_files_group_into_the_modules_the_code_is_built_from() -> None:
    assert area_of("app/modules/live/services.py") == "live"
    assert area_of("app/kernel/http/endpoint.py") == "kernel"
    assert area_of("app/modules/__init__.py") == "app"
    assert area_of("app/wsgi.py") == "app"
    total, areas = aggregate(_report({"app/modules/live/a.py": _file(1, 4), "app/modules/live/b.py": _file(3, 4)}))
    assert areas["live"].percent == 50.0 and total.percent == 50.0


def test_a_module_below_its_floor_fails_by_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tools.coverage_report import ROOT, tomllib

    floors = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["neotv"]["coverage"][
        "modules"
    ]
    files = {f"app/modules/{name}/x.py": _file(99, 100) for name in floors if name not in {"kernel", "shared_kernel"}}
    files |= {"app/kernel/x.py": _file(99, 100), "app/shared_kernel/x.py": _file(99, 100)}
    path = tmp_path / "coverage.json"

    path.write_text(json.dumps(_report(files)))
    assert main([str(path), "--badge", str(tmp_path / "badge.json")]) == 0
    assert json.loads((tmp_path / "badge.json").read_text())["message"] == "99%"

    files["app/modules/live/x.py"] = _file(10, 100)  # live drops far below its floor
    path.write_text(json.dumps(_report(files)))
    assert main([str(path)]) == 1
    assert "::error title=Coverage::live: 10.0%" in capsys.readouterr().out


def test_a_new_module_without_a_floor_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_report({"app/modules/brandnew/x.py": _file(100, 100)})))
    assert main([str(path)]) == 1
    assert "no floor configured for: brandnew" in capsys.readouterr().out
