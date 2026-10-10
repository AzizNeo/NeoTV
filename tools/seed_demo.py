"""Idempotent demo data (replaces Scripts/database/seed_live.py).

    python -m tools.seed_demo            # public test VODs + public live test streams (external sources)
    python -m tools.seed_demo --ingest   # also an RTMP ingest channel; prints its one-time key

Goes through the module services (same validation, events and audit as the
admin API) — never through raw SQL.
"""

from __future__ import annotations

import argparse
import sys

DEMO_VOD = (
    ("Sintel", "https://bitdash-a.akamaihd.net/content/sintel/hls/playlist.m3u8", "Movies"),
    ("Big Buck Bunny", "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8", "Movies"),
    (
        "Tears of Steel",
        "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
        "Movies",
    ),
)
# Public test streams published for player developers (no broadcast content).
DEMO_LIVE = (
    ("Akamai Live Test", "https://cph-p2p-msl.akamaized.net/hls/live/2000341/test/master.m3u8", "general"),
    ("Unified Streaming Live Test", "https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8", "general"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ingest", action="store_true", help="also create an RTMP ingest test channel")
    args = parser.parse_args(argv)

    from app.kernel.container import resolve
    from app.wsgi import app

    with app.app_context():
        from app.modules.catalog.services import CatalogAdminService, DuplicateChannelError
        from app.modules.live.services import LiveChannelService

        catalog = resolve(CatalogAdminService)
        for name, url, group in DEMO_VOD:
            try:
                catalog.add_channel(
                    name=name, stream_url=url, logo=None, group=group, kind="vod", rating="general", delivery="proxy"
                )
                print(f"catalog  + {name}")
            except DuplicateChannelError:
                print(f"catalog  = {name} (exists)")

        live = resolve(LiveChannelService)
        existing = {c.name for c in live.list_admin()}
        for order, (name, url, rating) in enumerate(DEMO_LIVE, start=1):
            if name in existing:
                print(f"live     = {name} (exists)")
                continue
            live.create(
                name=name,
                description=None,
                logo=None,
                source_type="external",
                upstream_url=url,
                delivery="proxy",
                rating=rating,
                epg_channel_id=None,
                sort_order=order,
            )
            print(f"live     + {name}")
        if args.ingest and "Test Ingest" not in existing:
            _, key = live.create(
                name="Test Ingest",
                description="OBS / tools.streaming.test_broadcast",
                logo=None,
                source_type="ingest",
                upstream_url=None,
                delivery="proxy",
                rating="general",
                epg_channel_id=None,
                sort_order=99,
            )
            print(f"live     + Test Ingest — ingest key (shown once): {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
