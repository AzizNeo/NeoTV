"""Pure rules and named errors of the titles module (no Flask, no SQLAlchemy).

A *title* is the storefront layer over playable content: a movie, or a series of
seasons and episodes, with synopsis, year, genres and artwork. Titles never own
streams — every movie / episode points at an existing playable ``ContentRef``
(``catalog:42`` …), so playback, DRM, stream limits and watch history are reused
unchanged.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.shared_kernel.content import ContentRef, InvalidContentRefError
from app.shared_kernel.ratings import RATINGS

NAMESPACE = "titles"

MAX_NAME = 200
MAX_SYNOPSIS = 4000
MAX_GENRES = 8
MAX_SEASONS = 100
MAX_EPISODES_PER_SEASON = 500
YEAR_RANGE = (1888, 2100)  # first surviving film … far enough ahead for announced releases
RUNTIME_RANGE = (1, 1000)  # minutes

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_MAX = 80
#: Path segments of /api/v1/titles/<…> that are not titles (see http.py).
RESERVED_SLUGS = frozenset({"admin", "featured", "genres", "rails"})
# Turkish letters that NFKD does not decompose into ASCII.
_TRANSLIT = str.maketrans({"ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g", "ç": "c", "Ç": "c",
                           "ö": "o", "Ö": "o", "ü": "u", "Ü": "u"})  # fmt: skip


class TitleKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"


# ── Errors ──────────────────────────────────────────────────────────────────
class TitlesError(Exception):
    def __init__(self, message: str = "", *, details: object = None) -> None:
        super().__init__(message or self.__class__.__name__)
        self.details = details


class TitleNotFoundError(TitlesError):
    pass


class InvalidTitleError(TitlesError):
    """The title document breaks a rule; ``details`` lists every violation (not just the first)."""


class RatingConflictError(TitlesError):
    """A kids-visible title over a source kids may not play. ``source_ratings`` maps each offending ref to its rating."""

    def __init__(self, message: str, *, source_ratings: dict[str, str]) -> None:
        super().__init__(message, details=[f"play_ref {r!r}: rated {v}" for r, v in sorted(source_ratings.items())])
        self.source_ratings = source_ratings


class PlaySourceNotFoundError(TitlesError):
    """A movie/episode points at content that does not exist or is not playable on demand."""


# ── Value helpers ───────────────────────────────────────────────────────────
def slugify(text: str) -> str:
    """``"Çılgın Şehir 2"`` → ``"cilgin-sehir-2"`` (stable, URL-safe, ASCII)."""
    ascii_text = unicodedata.normalize("NFKD", text.translate(_TRANSLIT)).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:_SLUG_MAX].rstrip("-")


def valid_slug(slug: str) -> bool:
    return len(slug) <= _SLUG_MAX and bool(_SLUG.fullmatch(slug))


def image_ok(url: str | None) -> bool:
    """Artwork is HTTPS or a same-origin path — never ``javascript:``/``data:``/plain HTTP (mixed content)."""
    return url is None or url.startswith("https://") or (url.startswith("/") and not url.startswith("//"))


# ── The aggregate as a document ─────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class EpisodeDraft:
    number: int
    name: str
    play_ref: str | None
    synopsis: str | None = None
    runtime_minutes: int | None = None
    still_url: str | None = None


@dataclass(frozen=True, slots=True)
class SeasonDraft:
    number: int
    name: str | None = None
    episodes: tuple[EpisodeDraft, ...] = ()


@dataclass(frozen=True, slots=True)
class TitleDraft:
    """A whole title as one document: the admin API replaces the aggregate atomically."""

    slug: str
    kind: TitleKind
    name: str
    rating: str = "unrated"
    synopsis: str | None = None
    year: int | None = None
    runtime_minutes: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    play_ref: str | None = None  # movies only
    genres: tuple[str, ...] = ()
    featured_rank: int | None = None  # 1 = first slot of the home hero; None = not featured
    is_published: bool = True
    seasons: tuple[SeasonDraft, ...] = field(default=())

    def play_refs(self) -> set[str]:
        refs = {self.play_ref} if self.play_ref else set()
        refs |= {e.play_ref for s in self.seasons for e in s.episodes if e.play_ref}
        return refs


def validate(draft: TitleDraft) -> None:
    """Raise one :class:`InvalidTitleError` carrying *every* violation, so an editor fixes all at once."""
    problems: list[str] = []
    add = problems.append

    if not valid_slug(draft.slug):
        add("slug: lowercase letters, digits and single dashes, at most 80 characters")
    elif draft.slug in RESERVED_SLUGS:
        add(f"slug: {draft.slug!r} is reserved")
    if not draft.name.strip() or len(draft.name) > MAX_NAME:
        add(f"name: 1–{MAX_NAME} characters")
    if draft.rating not in RATINGS:
        add(f"rating: one of {', '.join(RATINGS)}")
    if draft.synopsis is not None and len(draft.synopsis) > MAX_SYNOPSIS:
        add(f"synopsis: at most {MAX_SYNOPSIS} characters")
    if draft.year is not None and not YEAR_RANGE[0] <= draft.year <= YEAR_RANGE[1]:
        add(f"year: {YEAR_RANGE[0]}–{YEAR_RANGE[1]}")
    _runtime(draft.runtime_minutes, "runtime_minutes", add)
    for label, url in (("poster_url", draft.poster_url), ("backdrop_url", draft.backdrop_url)):
        if not image_ok(url):
            add(f"{label}: https:// URL or same-origin path")
    if len(draft.genres) > MAX_GENRES:
        add(f"genres: at most {MAX_GENRES}")
    if any(not slugify(g) for g in draft.genres):
        add("genres: every genre needs at least one letter or digit")
    if draft.featured_rank is not None and draft.featured_rank < 1:
        add("featured_rank: 1 or more")

    if draft.kind is TitleKind.MOVIE:
        if draft.seasons:
            add("seasons: only series have seasons")
        if draft.is_published and not draft.play_ref:
            add("play_ref: a published movie needs something to play")
    else:
        if draft.play_ref:
            add("play_ref: a series plays per episode")
        if draft.runtime_minutes is not None:
            add("runtime_minutes: set it per episode for a series")
        _seasons(draft.seasons, add)
        if draft.is_published and not any(e.play_ref for s in draft.seasons for e in s.episodes):
            add("seasons: a published series needs at least one playable episode")

    for ref in sorted(draft.play_refs()):
        try:
            parsed = ContentRef.parse(ref)
        except InvalidContentRefError:
            add(f"play_ref {ref!r}: expected '<namespace>:<id>'")
            continue
        if parsed.namespace == NAMESPACE:
            add(f"play_ref {ref!r}: a title cannot play another title")

    if problems:
        raise InvalidTitleError("Title document is invalid", details=problems)


Report = Callable[[str], None]


def _runtime(value: int | None, label: str, report: Report) -> None:
    if value is not None and not RUNTIME_RANGE[0] <= value <= RUNTIME_RANGE[1]:
        report(f"{label}: {RUNTIME_RANGE[0]}–{RUNTIME_RANGE[1]} minutes")


def _seasons(seasons: Sequence[SeasonDraft], report: Report) -> None:
    if len(seasons) > MAX_SEASONS:
        report(f"seasons: at most {MAX_SEASONS}")
    numbers = [s.number for s in seasons]
    if len(set(numbers)) != len(numbers):
        report("seasons: season numbers must be unique")
    for season in seasons:
        where = f"season {season.number}"
        if season.number < 0:
            report(f"{where}: number 0 (specials) or more")
        if season.name is not None and len(season.name) > MAX_NAME:
            report(f"{where}: name at most {MAX_NAME} characters")
        if len(season.episodes) > MAX_EPISODES_PER_SEASON:
            report(f"{where}: at most {MAX_EPISODES_PER_SEASON} episodes")
        ep_numbers = [e.number for e in season.episodes]
        if len(set(ep_numbers)) != len(ep_numbers):
            report(f"{where}: episode numbers must be unique")
        for ep in season.episodes:
            at = f"{where} episode {ep.number}"
            if ep.number < 1:
                report(f"{at}: number 1 or more")
            if not ep.name.strip() or len(ep.name) > MAX_NAME:
                report(f"{at}: name 1–{MAX_NAME} characters")
            if ep.synopsis is not None and len(ep.synopsis) > MAX_SYNOPSIS:
                report(f"{at}: synopsis at most {MAX_SYNOPSIS} characters")
            _runtime(ep.runtime_minutes, f"{at} runtime_minutes", report)
            if not image_ok(ep.still_url):
                report(f"{at}: still_url must be an https:// URL or same-origin path")
