"""Pure rules of the TMDB importer (no Flask, no HTTP, no SQLAlchemy).

TMDB is a *source of metadata*, never the owner of a title: the importer turns TMDB data into
a titles document and hands it to titles' own use case (capability ``titles.admin``), so
every import goes through the same validation, source checks and kids rule as a manual edit.

What an import may change: names, synopses (+ English translations), year, runtime, artwork,
genres, episode names / synopses / stills. What it never changes on an existing title: the
slug, kind, rating, play sources, featured slot and published flag — those are editorial.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.modules.titles.api import EpisodeDraft, LocalizedText, SeasonDraft, TitleDraft, TitleKind

IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_SIZE, BACKDROP_SIZE, STILL_SIZE = "w500", "w1280", "w300"
MAX_NAME, MAX_SYNOPSIS = 200, 4000
#: TMDB language codes for the platform's locales (the first one is the original).
LANGUAGES = {"tr": "tr-TR", "en": "en-US"}


class TmdbError(Exception):
    def __init__(self, message: str = "", *, details: object = None) -> None:
        super().__init__(message)
        self.details = details


class TmdbNotConfiguredError(TmdbError):
    """No TMDB_READ_TOKEN: the importer is installed but has no credentials."""


class TmdbUnavailableError(TmdbError):
    """TMDB did not answer usefully (network, rate limit, 5xx, rejected token)."""


class TmdbNotFoundError(TmdbError):
    """No such movie / series on TMDB."""


class TmdbKindMismatchError(TmdbError):
    """Linking a movie to a series (or the reverse)."""


class TmdbLinkNotFoundError(TmdbError):
    """The title is not linked to TMDB."""


# ── What TMDB tells us (already parsed, per language) ───────────────────────
@dataclass(frozen=True, slots=True)
class Text:
    name: str
    synopsis: str | None = None


@dataclass(frozen=True, slots=True)
class GenreMeta:
    tmdb_id: int
    names: dict[str, str]  # locale → name


@dataclass(frozen=True, slots=True)
class EpisodeMeta:
    number: int
    texts: dict[str, Text]
    runtime_minutes: int | None = None
    still_url: str | None = None


@dataclass(frozen=True, slots=True)
class SeasonMeta:
    number: int
    names: dict[str, str]
    episodes: tuple[EpisodeMeta, ...] = ()


@dataclass(frozen=True, slots=True)
class TitleMeta:
    tmdb_id: int
    kind: TitleKind
    texts: dict[str, Text]  # locale → name + synopsis
    year: int | None = None
    runtime_minutes: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    genres: tuple[GenreMeta, ...] = ()
    seasons: tuple[SeasonMeta, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class SearchHit:
    tmdb_id: int
    kind: TitleKind
    name: str
    original_name: str
    year: int | None
    overview: str | None
    poster_url: str | None


# ── Mapping helpers ─────────────────────────────────────────────────────────
def image(path: str | None, size: str) -> str | None:
    return f"{IMAGE_BASE}/{size}{path}" if path and path.startswith("/") else None


def year_of(date: str | None) -> int | None:
    try:
        return int((date or "")[:4]) or None
    except ValueError:
        return None


def clean(text: str | None, limit: int) -> str | None:
    text = " ".join((text or "").split())
    return text[:limit] if text else None


# ── The merge ───────────────────────────────────────────────────────────────
def merge(
    existing: TitleDraft | None,
    slug: str,
    meta: TitleMeta,
    *,
    original: str,
    play_ref: str | None = None,
) -> TitleDraft:
    """A titles document from TMDB metadata, keeping everything editorial of ``existing``.

    ``original`` is the default locale (its text fills the document's own fields; the others
    become translations). A new movie without ``play_ref`` and a new series are created
    unpublished: an editor attaches sources first. Episodes are enriched by (season, number);
    a new series gets TMDB's episode list as announced (not yet playable) episodes.
    """
    if existing is not None and existing.kind is not meta.kind:
        raise TmdbKindMismatchError(
            f"'{slug}' is a {existing.kind} but TMDB {meta.tmdb_id} is a {meta.kind}",
            details={"title": str(existing.kind), "tmdb": str(meta.kind)},
        )
    base = _text(meta.texts, original)
    if base is None:
        raise TmdbNotFoundError(f"TMDB {meta.tmdb_id} has no name")
    translations = {
        locale: LocalizedText(name=t.name, synopsis=t.synopsis)
        for locale, t in sorted(meta.texts.items())
        if locale != original and t.name
    }
    genres = tuple(dict.fromkeys(g.names.get(original) or next(iter(g.names.values())) for g in meta.genres if g.names))
    draft = existing or TitleDraft(
        slug=slug,
        kind=meta.kind,
        name=base.name,
        play_ref=play_ref if meta.kind is TitleKind.MOVIE else None,
        is_published=meta.kind is TitleKind.MOVIE and play_ref is not None,
    )
    return replace(
        draft,
        name=base.name,
        synopsis=base.synopsis or (existing.synopsis if existing else None),
        year=meta.year or draft.year,
        runtime_minutes=(meta.runtime_minutes or draft.runtime_minutes) if meta.kind is TitleKind.MOVIE else None,
        poster_url=meta.poster_url or draft.poster_url,
        backdrop_url=meta.backdrop_url or draft.backdrop_url,
        genres=genres[:8] or draft.genres,
        translations=translations,
        seasons=_seasons(draft.seasons, meta.seasons, original, announce=existing is None),
    )


def _text(texts: dict[str, Text], locale: str) -> Text | None:
    chosen = texts.get(locale) or next((t for t in texts.values() if t.name), None)
    if chosen is None or not chosen.name:
        return None
    return Text(name=chosen.name[:MAX_NAME], synopsis=clean(chosen.synopsis, MAX_SYNOPSIS))


def _seasons(
    current: tuple[SeasonDraft, ...], metas: tuple[SeasonMeta, ...], original: str, *, announce: bool
) -> tuple[SeasonDraft, ...]:
    by_number = {m.number: m for m in metas}
    out = [_enrich_season(s, by_number.get(s.number), original) for s in current]
    if announce:  # a brand-new series: TMDB's seasons, every episode announced
        out += [
            SeasonDraft(
                number=m.number,
                name=m.names.get(original),
                episodes=tuple(_announced(e, original) for e in m.episodes[:500]),
            )
            for m in metas[:100]
            if m.number not in {s.number for s in current}
        ]
    return tuple(out)


def _enrich_season(season: SeasonDraft, meta: SeasonMeta | None, original: str) -> SeasonDraft:
    if meta is None:
        return season
    episodes = {e.number: e for e in meta.episodes}
    return replace(
        season,
        name=season.name or meta.names.get(original),
        episodes=tuple(_enrich_episode(e, episodes.get(e.number), original) for e in season.episodes),
    )


def _enrich_episode(episode: EpisodeDraft, meta: EpisodeMeta | None, original: str) -> EpisodeDraft:
    if meta is None:
        return episode
    base = _text(meta.texts, original)
    return replace(
        episode,
        name=base.name if base else episode.name,
        synopsis=(base.synopsis if base and base.synopsis else episode.synopsis),
        runtime_minutes=meta.runtime_minutes or episode.runtime_minutes,
        still_url=meta.still_url or episode.still_url,
        translations=_episode_translations(meta, original),
    )


def _announced(meta: EpisodeMeta, original: str) -> EpisodeDraft:
    base = _text(meta.texts, original) or Text(name=f"{meta.number}")
    return EpisodeDraft(
        number=meta.number,
        name=base.name,
        play_ref=None,
        synopsis=base.synopsis,
        runtime_minutes=meta.runtime_minutes,
        still_url=meta.still_url,
        translations=_episode_translations(meta, original),
    )


def _episode_translations(meta: EpisodeMeta, original: str) -> dict[str, LocalizedText]:
    return {
        locale: LocalizedText(name=t.name[:MAX_NAME], synopsis=clean(t.synopsis, MAX_SYNOPSIS))
        for locale, t in sorted(meta.texts.items())
        if locale != original and t.name
    }
