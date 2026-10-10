"""IDE launcher shim → ``python -m tools.devctl run`` (re-executes inside .venv if present)."""

from __future__ import annotations

import sys

from tools.devctl import main

if __name__ == "__main__":
    sys.exit(main(["run", *sys.argv[1:]]))
