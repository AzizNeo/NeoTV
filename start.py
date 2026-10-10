"""Full development stack (API + worker + beat + frontend).

Thin shim kept for IDE configurations; the implementation lives in
``tools/devctl.py``. Unlike the legacy launcher it never kills processes it
did not start (RT-08).
"""

from __future__ import annotations

import sys

from tools.devctl import main

if __name__ == "__main__":
    sys.exit(main(["run", *sys.argv[1:]]))
