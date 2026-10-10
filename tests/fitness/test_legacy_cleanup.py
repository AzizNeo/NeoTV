"""The legacy tree must be gone, and the cleanup list must never endanger live code or data."""

from __future__ import annotations

from tools.cleanup_legacy import ROOT, legacy_paths, present

PROTECTED = (
    ".env",
    "instance",
    "docs",
    "app/kernel",
    "app/modules/_template",
    "migrations/revisions",
    "frontend/src/app",
)


def test_cleanup_list_never_targets_v2_code_or_user_data() -> None:
    for rel in legacy_paths():
        assert not rel.startswith(PROTECTED), f"legacy_paths.txt must not list {rel}"
        assert not rel.startswith(("/", "..")) and "\\" not in rel, f"{rel}: use repo-relative POSIX paths"
        assert rel != "Scripts", (
            "Scripts/ also holds the Windows virtualenv launchers — list its old project files only"
        )


def test_no_legacy_files_left() -> None:
    leftovers = [str(path.relative_to(ROOT)) for path in present()]
    assert not leftovers, (
        "Legacy files still on disk — run `python -m tools.cleanup_legacy --apply` "
        f"(reversible, moves them to .legacy_backup/): {leftovers}"
    )
