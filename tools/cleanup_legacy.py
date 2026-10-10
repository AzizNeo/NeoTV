"""Remove the pre-v2 files that the v2 tree superseded.

The v2 code was written *over* the legacy checkout; files that only existed in
the legacy layout (``app/core``, ``app/routes``, ``app/services``, old module
files, the broken ``migrations/versions`` folder, legacy scripts …) are still
on disk. Nothing imports them, but they mislead readers and tools.
``tests/fitness/test_legacy_cleanup.py`` fails until they are gone.

    python -m tools.cleanup_legacy            # dry run: list what would move
    python -m tools.cleanup_legacy --apply    # move into .legacy_backup/<UTC timestamp>/ (reversible)
    python -m tools.cleanup_legacy --purge    # delete permanently (after you are satisfied)

The list is explicit (``tools/legacy_paths.txt``): files you add later are never touched.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST_FILE = Path(__file__).with_name("legacy_paths.txt")
BACKUP_ROOT = ROOT / ".legacy_backup"


def legacy_paths() -> list[str]:
    lines = LIST_FILE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def present(root: Path = ROOT) -> list[Path]:
    """Legacy paths that still exist under ``root``."""
    return [root / rel for rel in legacy_paths() if (root / rel).exists()]


def _prune_upwards(directory: Path) -> None:
    """Remove a legacy directory left empty (stale __pycache__ ignored), then its empty parents."""
    while directory != ROOT and ROOT in directory.parents and directory.is_dir():
        if any(entry.name != "__pycache__" for entry in directory.iterdir()):
            return
        shutil.rmtree(directory / "__pycache__", ignore_errors=True)
        directory.rmdir()
        directory = directory.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="move legacy files into .legacy_backup/<timestamp>/")
    mode.add_argument("--purge", action="store_true", help="delete legacy files permanently")
    args = parser.parse_args(argv)

    found = present()
    if not found:
        print("legacy cleanup: nothing to do — the tree is clean")
        return 0
    print(f"legacy cleanup: {len(found)} path(s)")
    for path in found:
        print(f"  - {path.relative_to(ROOT).as_posix()}")
    if not (args.apply or args.purge):
        print("dry run — re-run with --apply (reversible move) or --purge (delete)")
        return 0

    target = BACKUP_ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    touched_dirs: set[Path] = set()
    for path in found:
        rel = path.relative_to(ROOT)
        touched_dirs.add(path.parent)
        if args.purge:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        else:
            destination = target / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(destination))
    for directory in sorted(touched_dirs, key=lambda p: len(p.parts), reverse=True):
        _prune_upwards(directory)
    print("deleted" if args.purge else f"moved to {target.relative_to(ROOT).as_posix()}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
