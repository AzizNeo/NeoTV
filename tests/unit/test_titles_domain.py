"""titles domain rules: slugs, artwork URLs, and whole-document validation."""

from __future__ import annotations

import pytest

from app.modules.titles.domain import (
    EpisodeDraft,
    InvalidTitleError,
    SeasonDraft,
    TitleDraft,
    TitleKind,
    image_ok,
    slugify,
    validate,
)


def _movie(**kw: object) -> TitleDraft:
    base: dict[str, object] = {"slug": "sintel", "kind": TitleKind.MOVIE, "name": "Sintel", "play_ref": "catalog:2"}
    return TitleDraft(**{**base, **kw})  # type: ignore[arg-type]


def _series(*seasons: SeasonDraft, **kw: object) -> TitleDraft:
    base: dict[str, object] = {"slug": "shorts", "kind": TitleKind.SERIES, "name": "Shorts", "seasons": seasons}
    return TitleDraft(**{**base, **kw})  # type: ignore[arg-type]


def _problems(draft: TitleDraft) -> list[str]:
    with pytest.raises(InvalidTitleError) as info:
        validate(draft)
    return list(info.value.details)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Çılgın Şehir 2", "cilgin-sehir-2"),
        ("  Tears of Steel!  ", "tears-of-steel"),
        ("Ağır Ölü — Üç", "agir-olu-uc"),
        ("!!!", ""),
    ],
)
def test_slugify_is_ascii_and_stable(text: str, slug: str) -> None:
    assert slugify(text) == slug


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        (None, True),
        ("https://cdn.example.com/p.jpg", True),
        ("/demo/sintel.svg", True),
        ("http://cdn.example.com/p.jpg", False),  # mixed content
        ("//evil.example.com/p.jpg", False),  # protocol-relative = foreign origin
        ("javascript:alert(1)", False),
        ("data:image/svg+xml;base64,AAAA", False),
    ],
)
def test_artwork_must_be_https_or_same_origin(url: str | None, ok: bool) -> None:
    assert image_ok(url) is ok


def test_valid_movie_and_series_pass() -> None:
    validate(_movie(year=2010, runtime_minutes=15, genres=("Animasyon",), rating="teen"))
    validate(_series(SeasonDraft(1, episodes=(EpisodeDraft(1, "Pilot", "catalog:1"), EpisodeDraft(2, "Two", None)))))


def test_every_violation_is_reported_at_once() -> None:
    problems = _problems(_movie(slug="Bad Slug", name="", rating="x", year=1700, poster_url="http://x/p.jpg"))
    assert len(problems) == 5, problems


def test_movie_and_series_shapes_are_enforced() -> None:
    assert any("needs something to play" in p for p in _problems(_movie(play_ref=None)))
    validate(_movie(play_ref=None, is_published=False))  # drafts may be incomplete
    assert any("only series have seasons" in p for p in _problems(_movie(seasons=(SeasonDraft(1),))))
    assert any("plays per episode" in p for p in _problems(_series(play_ref="catalog:1")))
    assert any("playable episode" in p for p in _problems(_series(SeasonDraft(1))))


def test_numbers_must_be_unique_and_refs_well_formed() -> None:
    dup = _series(
        SeasonDraft(1, episodes=(EpisodeDraft(1, "A", "catalog:1"), EpisodeDraft(1, "B", "catalog:2"))),
        SeasonDraft(1, episodes=(EpisodeDraft(1, "C", "catalog:3"),)),
    )
    problems = _problems(dup)
    assert any("season numbers must be unique" in p for p in problems)
    assert any("episode numbers must be unique" in p for p in problems)
    assert any("expected '<namespace>:<id>'" in p for p in _problems(_movie(play_ref="catalog-2")))
    assert any("cannot play another title" in p for p in _problems(_movie(play_ref="titles:1")))
