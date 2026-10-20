"""A synthetic catch-up archive for development and browser tests (ADR-0012).

    python -m tools.seed_archive --channel "Akamai Live" [--days 3] [--minutes 180]

Switches the channel's archive on (as the first administrator, rights confirmed) and writes
placeholder MPEG-TS segments for the last ``--minutes`` — what the recorder would have written —
so the guide offers "watch again" and the archive playlists can be exercised without recording a
third-party stream. The segments hold null packets, not pictures: this tests the path, not the
picture. Refused in production, where only the recorder writes the archive.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta

#: One MPEG-TS null packet (PID 0x1FFF): a valid transport stream that carries nothing.
NULL_PACKET = b"\x47\x1f\xff\x10" + b"\xff" * 184


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", required=True, help="live channel name")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--minutes", type=int, default=180)
    args = parser.parse_args(argv)
    if os.environ.get("ENV", "").lower() == "prod":
        raise SystemExit("refused: synthetic recordings do not belong in production")

    from sqlalchemy import select

    from app.kernel.container import resolve
    from app.kernel.db import db
    from app.kernel.settings import Settings
    from app.kernel.time import Clock
    from app.modules.identity.models import User
    from app.modules.live.archive import SEGMENT_SECONDS, ArchiveStorage
    from app.modules.live.services import LiveChannelService
    from app.wsgi import app

    with app.app_context():
        live = resolve(LiveChannelService)
        channel = next((c for c in live.list_admin() if c.name == args.channel), None)
        if channel is None:
            raise SystemExit(f"no live channel named {args.channel!r} (run tools.seed_demo first)")
        admin_id = db.session.execute(select(User.id).where(User.role == "admin").order_by(User.id)).scalar()
        live.set_archive(
            channel.id,
            days=args.days,
            rights_confirmed=True,
            actor_id=int(admin_id or 0),
            max_days=resolve(Settings).archive_max_days,
        )
        storage = resolve(ArchiveStorage)
        now = resolve(Clock).now().replace(microsecond=0)
        moment, written = now - timedelta(minutes=args.minutes), 0
        while moment < now:
            path = storage.channel_dir(channel.id) / storage.segment_name(moment)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(NULL_PACKET * 10)
                written += 1
            moment += timedelta(seconds=SEGMENT_SECONDS)
        print(f"archive  + {args.channel}: {args.days} days, {written} synthetic segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
