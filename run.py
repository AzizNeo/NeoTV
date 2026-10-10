"""Backend only (production-grade WSGI server). Kept for existing habits/IDE configs.

    python run.py            → waitress on HOST:PORT (default 127.0.0.1:5000)

For the whole dev stack use:  python -m tools.devctl run
"""

from __future__ import annotations

import os


def main() -> None:
    from waitress import serve

    from app.wsgi import app

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "8"))
    print(f"NeoTV API → http://{host}:{port}  (threads={threads})")
    serve(app, host=host, port=port, threads=threads, ident="neotv")


if __name__ == "__main__":
    main()
