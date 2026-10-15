"""Regenerate (or --check) the hash-locked dependency files from requirements*.txt.

    python -m tools.lock_deps          # after editing requirements.txt / requirements-dev.txt
    python -m tools.lock_deps --check  # CI: fail if a lock no longer matches its requirements
    python -m tools.lock_deps --upgrade  # deliberately move every pin to the newest release

Pins are *sticky*: a compile starts from the current lock (uv keeps its versions while they
still satisfy the requirements), so ``--check`` fails only when someone edited a
requirements file without re-locking — never just because PyPI published something new.

One *universal* lock serves Windows and Linux (platform markers such as
``colorama ; sys_platform == 'win32'`` are kept). Needs ``uv`` (pip install uv).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKS = {"requirements.lock": "requirements.txt", "requirements-dev.lock": "requirements-dev.txt"}
PYTHON_FLOOR = "3.12"


def _compile(source: str, out: Path, *, upgrade: bool = False) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit("uv is not installed: pip install uv")
    subprocess.run(
        [uv, "pip", "compile", source, "--universal", "--python-version", PYTHON_FLOOR,
         "--generate-hashes", "--no-header", "-q", "-o", str(out), *(["--upgrade"] if upgrade else [])],
        cwd=ROOT,
        check=True,
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if any lock differs from a fresh compile")
    parser.add_argument("--upgrade", action="store_true", help="ignore current pins and take the newest releases")
    args = parser.parse_args(argv)
    stale = []
    for lock, source in LOCKS.items():
        target = ROOT / lock
        if not args.check:
            _compile(source, target, upgrade=args.upgrade)
            print(f"wrote {lock}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / lock
            if target.exists():
                shutil.copyfile(target, fresh)  # start from the current pins (sticky)
            _compile(source, fresh)
            if not target.exists() or fresh.read_text() != target.read_text():
                stale.append(lock)
    if stale:
        print(f"stale lock(s): {', '.join(stale)} — run `python -m tools.lock_deps` and commit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
