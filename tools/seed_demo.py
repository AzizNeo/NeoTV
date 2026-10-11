"""Idempotent demo data: legal test content, original artwork, a programme guide.

    python -m tools.seed_demo            # VOD + live test channels (+ today's guide)
    python -m tools.seed_demo --ingest   # also an RTMP ingest channel; prints its one-time key

Content is limited to material published for exactly this purpose: Blender
Foundation open movies (CC BY) and public player test streams. Artwork comes
from ``tools.demo_art`` (served by the frontend under ``/demo/``).

Goes through the module services (same validation, events and audit as the
admin API) — never through raw SQL.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

#: (title, stream, group, artwork slug) — Blender open movies: © Blender Foundation, CC BY.
DEMO_VOD = (
    ("Big Buck Bunny", "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8", "Open Movies", "big-buck-bunny"),
    ("Sintel", "https://bitdash-a.akamaihd.net/content/sintel/hls/playlist.m3u8", "Open Movies", "sintel"),
    (
        "Tears of Steel",
        "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
        "Open Movies",
        "tears-of-steel",
    ),
    (
        "BipBop",
        "https://devstreaming-cdn.apple.com/videos/streaming/examples/bipbop_16x9/bipbop_16x9_variant.m3u8",
        "Test Streams",
        "bipbop-basic",
    ),
    (
        "BipBop Advanced",
        "https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8",
        "Test Streams",
        "bipbop-advanced",
    ),
)

#: Public test streams published for player developers (no broadcast content).
DEMO_LIVE = (
    ("Akamai Live", "https://cph-p2p-msl.akamaized.net/hls/live/2000341/test/master.m3u8", "live-akamai"),
    ("Unified Live", "https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8", "live-unified"),
)

#: Looping guide used for every demo live channel (title, minutes).
GUIDE = (("Test Card", 30), ("Network Loop", 60), ("Encoder Check", 30), ("Night Shift", 90), ("Signal Report", 30))


def _art(slug: str) -> str:
    return f"/demo/{slug}.svg"  # same-origin: works on any host the frontend is served from


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ingest", action="store_true", help="also create an RTMP ingest test channel")
    args = parser.parse_args(argv)

    from app.kernel.container import resolve
    from app.kernel.time import Clock
    from app.wsgi import app

    with app.app_context():
        from app.modules.catalog.services import CatalogAdminService, DuplicateChannelError
        from app.modules.live.services import EpgService, LiveChannelService

        catalog = resolve(CatalogAdminService)
        for name, url, group, slug in DEMO_VOD:
            try:
                catalog.add_channel(
                    name=name,
                    stream_url=url,
                    logo=_art(slug),
                    group=group,
                    kind="vod",
                    rating="general",
                    delivery="proxy",
                )
                print(f"catalog  + {name}")
            except DuplicateChannelError:
                print(f"catalog  = {name} (exists)")

        live = resolve(LiveChannelService)
        existing = {c.name: c.id for c in live.list_admin()}
        for order, (name, url, slug) in enumerate(DEMO_LIVE, start=1):
            if name in existing:
                print(f"live     = {name} (exists)")
                continue
            created, _ = live.create(
                name=name,
                description="Public HLS test stream",
                logo=_art(slug),
                source_type="external",
                upstream_url=url,
                delivery="proxy",
                rating="general",
                epg_channel_id=None,
                sort_order=order,
            )
            existing[name] = created.id
            print(f"live     + {name}")

        _seed_guide(resolve(EpgService), resolve(Clock), [existing[name] for name, _, _ in DEMO_LIVE])

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


def _seed_guide(epg: object, clock: object, channel_ids: list[int]) -> None:
    """Fill the next ~12 hours (from the last full hour) unless a guide already exists."""
    now = clock.now()  # type: ignore[attr-defined]
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    end = start + timedelta(hours=13)
    if epg.guide(start=start, end=end, channel_ids=channel_ids):  # type: ignore[attr-defined]
        print("guide    = (exists)")
        return
    for offset, channel_id in enumerate(channel_ids):
        cursor, i = start, offset  # stagger channels so the grid is not uniform
        while cursor < end:
            title, minutes = GUIDE[i % len(GUIDE)]
            stop = cursor + timedelta(minutes=minutes)
            epg.add(channel_id=channel_id, title=title, description=None, starts_at=cursor, ends_at=stop)  # type: ignore[attr-defined]
            cursor, i = stop, i + 1
    print(f"guide    + {len(channel_ids)} channels, next 12h")


if __name__ == "__main__":
    sys.exit(main())
