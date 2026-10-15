"""Idempotent demo data: legal test content, original artwork, a programme guide.

    python -m tools.seed_demo            # VOD + live test channels (+ today's guide)
    python -m tools.seed_demo --ingest   # also an RTMP ingest channel; prints its one-time key
    python -m tools.seed_demo --tmdb     # also import the open movies' metadata + artwork from TMDB
                                         # (needs TMDB_READ_TOKEN in .env)

Content is limited to material published for exactly this purpose: Blender
Foundation open movies (CC BY) and public player test streams. Artwork comes
from ``tools.demo_art`` (served by the frontend under ``/demo/``). With the
``titles`` module enabled, the VOD also gets storefront pages (synopsis, genres,
a series with episodes).

Goes through the module services (same validation, events and audit as the
admin API) — never through raw SQL.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.catalog.services import CatalogAdminService

#: (title, stream, group, artwork slug) — Blender open movies: © Blender Foundation, CC BY.
DEMO_VOD = (
    ("Big Buck Bunny", "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8", "Open Movies", "big-buck-bunny"),
    ("Sintel", "https://d2zihajmogu5jn.cloudfront.net/sintel/master.m3u8", "Open Movies", "sintel"),
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

#: Demo sources that stopped working (host now answers 403/404). Re-running the seed retires their
#: channels so an existing database moves to the replacement instead of keeping a dead duplicate.
RETIRED_URLS = frozenset(
    {
        "https://bitdash-a.akamaihd.net/content/sintel/hls/playlist.m3u8",  # Bitmovin: 403 since 2026
    }
)

#: Public test streams published for player developers (no broadcast content).
DEMO_LIVE = (
    ("Akamai Live", "https://cph-p2p-msl.akamaized.net/hls/live/2000341/test/master.m3u8", "live-akamai"),
    ("Unified Live", "https://demo.unified-streaming.com/k8s/live/stable/live.isml/.m3u8", "live-unified"),
)


@dataclass(frozen=True, slots=True)
class DemoTitle:
    """Storefront document over DEMO_VOD (``titles`` module). Synopses are original, written for this demo."""

    slug: str
    name: str
    year: int
    rating: str
    genres: tuple[str, ...]
    synopsis: str
    play: str | None = None  # movie: a DEMO_VOD title
    runtime_minutes: int | None = None
    featured_rank: int | None = None
    episodes: tuple[tuple[str, str], ...] = ()  # series, season 1: (DEMO_VOD title, episode synopsis)
    en: tuple[str, str] | None = None  # English (name, synopsis)
    episodes_en: tuple[str, ...] = ()  # English episode synopses, in order


DEMO_TITLES = (
    DemoTitle(
        "tears-of-steel", "Tears of Steel", 2012, "teen", ("Bilim Kurgu", "Aksiyon"),
        "Gelecekteki Amsterdam'da bir grup bilim insanı, dünyayı makinelerden kurtarmak için geçmişteki tek "
        "bir anı yeniden yaşamaya çalışır.",
        play="Tears of Steel", runtime_minutes=12, featured_rank=1,
        en=("Tears of Steel", "In a future Amsterdam, a group of scientists tries to save the world from machines "
            "by reliving a single moment from the past."),
    ),
    DemoTitle(
        "sintel", "Sintel", 2010, "teen", ("Animasyon", "Fantastik"),
        "Yalnız bir savaşçı kız, büyüttüğü yavru ejderhayı bulmak için karlı dağları ve tehlikeli şehirleri "
        "aşan uzun bir yolculuğa çıkar.",
        play="Sintel", runtime_minutes=15, featured_rank=2,
        en=("Sintel", "A lone young warrior crosses snowy mountains and dangerous cities on a long journey to find "
            "the baby dragon she raised."),
    ),
    DemoTitle(
        "big-buck-bunny", "Big Buck Bunny", 2008, "general", ("Animasyon", "Komedi"),
        "İri ve iyi kalpli bir tavşan, ormandaki üç yaramaz kemirgenin şakalarına kendi yöntemleriyle "
        "karşılık verir.",
        play="Big Buck Bunny", runtime_minutes=10, featured_rank=3,
        en=("Big Buck Bunny", "A big, good-hearted rabbit answers the pranks of three mischievous forest rodents "
            "in his own way."),
    ),
    DemoTitle(
        "test-streams", "Test Yayınları", 2016, "general", ("Teknik",),
        "Oynatıcı geliştiricileri için yayımlanan HLS test akışları: farklı çözünürlükler, codec'ler ve "
        "paketleme biçimleri.",
        episodes=(("BipBop", "Temel HLS akışı."), ("BipBop Advanced", "fMP4, çoklu ses ve altyazı.")),
        en=("Test Streams", "HLS test streams published for player developers: different resolutions, codecs and "
            "packaging formats."),
        episodes_en=("A basic HLS stream.", "fMP4, multiple audio tracks and subtitles."),
    ),
)  # fmt: skip

#: English names of the demo genres (the Turkish ones are the originals).
GENRES_EN = {
    "animasyon": "Animation", "aksiyon": "Action", "bilim-kurgu": "Science Fiction",
    "fantastik": "Fantasy", "komedi": "Comedy", "teknik": "Technical",
}  # fmt: skip

#: Looping guide used for every demo live channel (title, minutes).
GUIDE = (("Test Card", 30), ("Network Loop", 60), ("Encoder Check", 30), ("Night Shift", 90), ("Signal Report", 30))


def _art(slug: str) -> str:
    return f"/demo/{slug}.svg"  # same-origin: works on any host the frontend is served from


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ingest", action="store_true", help="also create an RTMP ingest test channel")
    parser.add_argument("--tmdb", action="store_true", help="import the open movies' metadata from TMDB")
    args = parser.parse_args(argv)

    from app.kernel.container import resolve
    from app.kernel.time import Clock
    from app.wsgi import app

    with app.app_context():
        from app.modules.catalog.services import CatalogAdminService, DuplicateChannelError
        from app.modules.live.services import EpgService, LiveChannelService

        catalog = resolve(CatalogAdminService)
        channels, _ = catalog.list_channels(page=1, per_page=200, search=None, include_inactive=False)
        for channel in channels:
            if channel.stream_url in RETIRED_URLS:
                catalog.remove_channel(channel.id)
                print(f"catalog  - {channel.name} (retired source)")

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

        failures = _seed_titles(catalog) if "titles" in app.extensions["modules"] else 0  # optional module
        if args.tmdb:
            failures += _link_tmdb() if "tmdb" in app.extensions["modules"] else _missing("tmdb")

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
    return 1 if failures else 0


#: Demo-only ordering for "make the title at least as strict as its source".
_STRICTNESS = {"general": 0, "teen": 1, "unrated": 2, "adult": 3}


def _seed_titles(catalog: CatalogAdminService) -> int:
    """Upsert the storefront documents — same validation as ``PUT /api/v1/titles/admin/titles/<slug>``.

    Reports each failing title and carries on; returns the number of failures.
    """
    from app.kernel.container import resolve
    from app.modules.titles.domain import (
        EpisodeDraft,
        LocalizedText,
        RatingConflictError,
        SeasonDraft,
        TitleDraft,
        TitleKind,
        TitlesError,
    )
    from app.modules.titles.services import TitleAdminService

    channels, _ = catalog.list_channels(page=1, per_page=200, search=None, include_inactive=False)
    ref = {c.name: f"catalog:{c.id}" for c in channels}
    service = resolve(TitleAdminService)
    failures = 0
    for t in DEMO_TITLES:
        season = SeasonDraft(
            number=1,
            episodes=tuple(
                EpisodeDraft(
                    number=n,
                    name=name,
                    synopsis=about,
                    play_ref=ref[name],
                    translations={"en": LocalizedText(name, t.episodes_en[n - 1])} if t.episodes_en else {},
                )
                for n, (name, about) in enumerate(t.episodes, start=1)
            ),
        )
        draft = TitleDraft(
            slug=t.slug,
            kind=TitleKind.SERIES if t.episodes else TitleKind.MOVIE,
            name=t.name,
            rating=t.rating,
            synopsis=t.synopsis,
            year=t.year,
            runtime_minutes=t.runtime_minutes,
            poster_url=_art(f"{t.slug}-poster"),
            backdrop_url=_art(f"{t.slug}-backdrop"),
            play_ref=ref[t.play] if t.play else None,
            genres=t.genres,
            featured_rank=t.featured_rank,
            seasons=(season,) if t.episodes else (),
            translations={"en": LocalizedText(*t.en)} if t.en else {},
        )
        try:
            try:
                created = service.upsert(draft)
            except RatingConflictError as conflict:
                # The demo source was re-rated locally (admin edit, playlist import …): follow the source —
                # the kids rule itself is never bypassed.
                rating = max(conflict.source_ratings.values(), key=lambda r: _STRICTNESS.get(r, len(_STRICTNESS)))
                print(f"titles   ~ {t.name}: rating {draft.rating!r} → {rating!r} (its source is rated {rating!r})")
                created = service.upsert(replace(draft, rating=rating))
        except TitlesError as err:
            failures += 1
            print(f"titles   ! {t.name}: {err}")
            for line in err.details if isinstance(err.details, list) else ():
                print(f"           - {line}")
            continue
        print(f"titles   {'+' if created else '='} {t.name}")
    for slug, name in GENRES_EN.items():
        with contextlib.suppress(TitlesError):  # genre unused if its titles failed above
            service.set_genre_names(slug, {"en": name})
    return failures


#: Demo title → its TMDB movie id (Blender open movies).
TMDB_IDS = {"tears-of-steel": 133701, "sintel": 45745, "big-buck-bunny": 10378}


def _link_tmdb() -> int:
    """Import names, synopses (TR + EN), artwork and genres from TMDB; editorial fields stay."""
    from app.kernel.container import resolve
    from app.modules.titles.api import TitleKind
    from app.modules.tmdb.domain import TmdbError
    from app.modules.tmdb.services import TmdbService

    service = resolve(TmdbService)
    if not service.configured:
        print("tmdb     ! TMDB_READ_TOKEN is not set in .env — skipped")
        return 1
    failures = 0
    for slug, tmdb_id in TMDB_IDS.items():
        try:
            service.link(slug, tmdb_id, TitleKind.MOVIE)
            print(f"tmdb     + {slug} <- TMDB {tmdb_id}")
        except TmdbError as err:
            failures += 1
            print(f"tmdb     ! {slug}: {type(err).__name__}: {err}")
    return failures


def _missing(module: str) -> int:
    print(f"{module:<8} ! module is disabled (DISABLED_MODULES) — skipped")
    return 1


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
