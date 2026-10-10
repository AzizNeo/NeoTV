"""Turn the tail of a failed CI log into a GitHub *annotation*.

Job logs live in blob storage that not every reader can reach; annotations are
shown on the run's summary page and returned by the checks API. One multi-line
::error:: (newlines encoded as %0A) keeps the failure readable in both places.

    pytest ... | tee out.log || { python tools/ci_report.py out.log; exit 1; }
"""

from __future__ import annotations

import sys
from pathlib import Path

KEEP = 60  # lines
MARKERS = ("FAILED", "ERROR", "Error", "assert", "Traceback", "FAIL", "smoke │")


def main(path: str) -> int:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    focus = [line for line in lines if any(m in line for m in MARKERS)][-KEEP:] or lines[-KEEP:]
    body = "%0A".join(line.replace("%", "%25").replace("\r", "") for line in focus)
    print(f"::error title={Path(path).stem} failed::{body}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
