"""Audit finding IDs cited in the code resolve to ADR-0010's finding index.

Comments such as "(SEC-08)" explain why code is written the way it is; the ID is only useful while
it leads somewhere. A typo, or a new ID that was never recorded, fails here by name and location.
"""

from __future__ import annotations

import re
import subprocess

from app.kernel.settings import PROJECT_ROOT

ADR = PROJECT_ROOT / "docs" / "adr" / "0010-from-audit-to-rewrite.md"
PREFIXES = ("SEC", "RT", "RES", "DATA", "ASY", "STR", "PERF", "CFG", "FE", "HYG", "TEST")
CITED = re.compile(rf"\b(?:{'|'.join(PREFIXES)})-\d{{2}}\b")
INDEXED = re.compile(r"^\| ((?:[A-Z]+)-\d{2}) \| P\d \|", re.M)


def _indexed() -> set[str]:
    return set(INDEXED.findall(ADR.read_text(encoding="utf-8")))


def _citations() -> dict[str, list[str]]:
    tracked = subprocess.run(
        ["git", "ls-files", "app", "frontend/src", "frontend/scripts", "migrations", "tools", "*.py"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    found: dict[str, list[str]] = {}
    for name in tracked:
        path = PROJECT_ROOT / name
        if path.suffix not in {".py", ".js", ".jsx", ".mjs"} or not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for finding in CITED.findall(line):
                found.setdefault(finding, []).append(f"{name}:{number}")
    return found


def test_the_index_lists_every_finding_once():
    rows = INDEXED.findall(ADR.read_text(encoding="utf-8"))
    assert len(rows) == len(set(rows)), "a finding appears twice in ADR-0010's index"
    assert len(rows) == 62


def test_every_cited_finding_is_in_the_index():
    unknown = {finding: where for finding, where in _citations().items() if finding not in _indexed()}
    assert not unknown, f"cited but not in docs/adr/0010-from-audit-to-rewrite.md: {unknown}"


def test_the_code_still_cites_findings():
    # Guards the test itself: a broken file filter would make the check above pass vacuously.
    assert len(_citations()) >= 20
