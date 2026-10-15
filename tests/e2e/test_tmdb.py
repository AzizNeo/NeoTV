"""tmdb end to end: search, import into titles (TR original + EN translation), refresh, unlink.

TMDB itself is faked (tests/support/tmdb_fake.py): no network, deterministic answers.
"""

from __future__ import annotations

from typing import Any

import fakeredis
import pytest
from flask import Flask

from app.modules.tmdb.client import EgressTransport, TmdbClient
from app.modules.tmdb.domain import TmdbNotConfiguredError, TmdbUnavailableError
from tests.support.client import Api
from tests.support.factory import make_app
from tests.support.tmdb_fake import MOVIE_ID, SHOW_ID, FakeTmdb

TITLES = "/api/v1/titles/admin/titles"
EN = {"Accept-Language": "en"}


@pytest.fixture
def fake() -> FakeTmdb:
    return FakeTmdb()


@pytest.fixture
def app(fake: FakeTmdb) -> Flask:
    flask_app = make_app(tmdb_read_token="test-token-not-real")
    flask_app.extensions["container"].override(TmdbClient, TmdbClient(fake))
    return flask_app


def test_unconfigured_importer_says_so_and_nothing_else_changes() -> None:
    api = Api(make_app())  # no TMDB_READ_TOKEN
    admin = api.user("boss", role="admin")
    assert api.get("/api/v1/tmdb/status", token=admin).data["configured"] is False
    reply = api.get("/api/v1/tmdb/search", token=admin, query_string={"query": "sintel"})
    assert (reply.status, reply.code) == (503, "METADATA_PROVIDER_NOT_CONFIGURED")


def test_search_is_admin_only_and_speaks_the_admin_language(api: Api, admin: str, viewer: str, fake: FakeTmdb) -> None:
    assert api.get("/api/v1/tmdb/search", token=viewer, query_string={"query": "x"}).code == "PERMISSION_DENIED"
    hits = api.get("/api/v1/tmdb/search", token=admin, query_string={"query": "sintel", "year": 2010}, headers=EN).data
    assert hits == [{
        "tmdb_id": MOVIE_ID, "kind": "movie", "name": "Sintel", "original_name": "Sintel", "year": 2010,
        "overview": "A girl searches for her lost dragon.", "poster_url": "https://image.tmdb.org/t/p/w500/sintel.jpg",
    }]  # fmt: skip
    assert fake.calls[-1] == (
        "/search/movie",
        {"query": "sintel", "language": "en-US", "include_adult": "false", "page": "1", "year": "2010"},
    )


def test_import_fills_metadata_but_never_editorial_fields(api: Api, admin: str, viewer: str) -> None:
    src = api.channel(admin, "Sintel source", rating="teen")
    doc = {"kind": "movie", "name": "Eski ad", "rating": "teen", "play_ref": f"catalog:{src['id']}", "featured_rank": 2}
    assert api.put(f"{TITLES}/sintel", token=admin, json=doc).status == 201

    link = api.put("/api/v1/tmdb/links/sintel", token=admin, json={"tmdb_id": MOVIE_ID, "kind": "movie"})
    assert link.status == 200 and link.data["tmdb_id"] == MOVIE_ID
    title = api.get(f"{TITLES}/sintel", token=admin).data
    assert (title["name"], title["synopsis"], title["year"], title["runtime_minutes"]) == (
        "Sintel", "Bir kız kayıp ejderhasını arar.", 2010, 15,
    )  # fmt: skip
    assert title["translations"] == {"en": {"name": "Sintel", "synopsis": "A girl searches for her lost dragon."}}
    assert title["poster_url"] == "https://image.tmdb.org/t/p/w500/sintel.jpg"
    assert title["genres"] == ["Animasyon", "Fantastik"]
    # editorial: untouched
    assert (title["rating"], title["play_ref"], title["featured_rank"], title["is_published"]) == (
        "teen", f"catalog:{src['id']}", 2, True,
    )  # fmt: skip
    en = api.get("/api/v1/titles/sintel", token=viewer, headers=EN).data
    assert (en["synopsis"], en["card"]["genres"]) == ("A girl searches for her lost dragon.", ["Animation", "Fantasy"])

    assert [link["slug"] for link in api.get("/api/v1/tmdb/links", token=admin).data] == ["sintel"]
    assert api.post("/api/v1/tmdb/links/sintel/refresh", token=admin).data["slug"] == "sintel"
    assert api.delete("/api/v1/tmdb/links/sintel", token=admin).status == 204
    assert api.post("/api/v1/tmdb/links/sintel/refresh", token=admin).code == "METADATA_LINK_NOT_FOUND"
    assert api.get(f"{TITLES}/sintel", token=admin).data["name"] == "Sintel"  # metadata stays


def test_a_new_series_arrives_as_a_draft_with_announced_episodes(api: Api, admin: str) -> None:
    created = api.put("/api/v1/tmdb/links/open-shorts", token=admin, json={"tmdb_id": SHOW_ID, "kind": "series"})
    assert created.status == 201 and created.data["created"] is True
    title = api.get(f"{TITLES}/open-shorts", token=admin).data
    assert (title["name"], title["is_published"]) == ("Açık Kısalar", False)  # nothing plays yet
    [season] = title["seasons"]  # season 0 (specials) has no episodes on TMDB here
    assert season["name"] == "1. Sezon"
    assert [(e["number"], e["name"], e["play_ref"]) for e in season["episodes"]] == [
        (1, "Başlangıç", None),
        (2, "Devam", None),
    ]
    assert season["episodes"][0]["translations"] == {"en": {"name": "Beginning", "synopsis": "The first episode."}}

    # An editor attaches a source to episode 1 and publishes; a refresh keeps that.
    ep = api.channel(admin, "Episode one")
    season["episodes"][0]["play_ref"] = f"catalog:{ep['id']}"
    body: dict[str, Any] = {k: v for k, v in title.items() if k != "slug"} | {"is_published": True}
    assert api.put(f"{TITLES}/open-shorts", token=admin, json=body).status == 200
    api.post("/api/v1/tmdb/links/open-shorts/refresh", token=admin)
    after = api.get(f"{TITLES}/open-shorts", token=admin).data
    assert after["is_published"] is True and after["seasons"][0]["episodes"][0]["play_ref"] == f"catalog:{ep['id']}"


def test_import_errors_are_named(api: Api, admin: str) -> None:
    src = api.channel(admin, "Film")
    api.put(f"{TITLES}/film", token=admin, json={"kind": "movie", "name": "Film", "play_ref": f"catalog:{src['id']}"})
    mismatch = api.put("/api/v1/tmdb/links/film", token=admin, json={"tmdb_id": SHOW_ID, "kind": "series"})
    assert (mismatch.status, mismatch.code) == (409, "METADATA_KIND_MISMATCH")
    missing = api.put("/api/v1/tmdb/links/film", token=admin, json={"tmdb_id": 1, "kind": "movie"})
    assert (missing.status, missing.code) == (404, "METADATA_NOT_FOUND")
    ghost = api.put(
        "/api/v1/tmdb/links/ghost", token=admin, json={"tmdb_id": MOVIE_ID, "kind": "movie", "play_ref": "catalog:999"}
    )
    assert ghost.code == "PLAY_SOURCE_NOT_FOUND"  # titles' own rules apply to imports too


# ── the client ─────────────────────────────────────────────────────────────


def test_answers_are_cached_for_a_day(fake: FakeTmdb) -> None:
    client = TmdbClient(fake, fakeredis.FakeRedis())
    from app.modules.titles.api import TitleKind

    for _ in range(3):
        client.search("sintel", TitleKind.MOVIE, year=None, locale="tr")
    assert len(fake.calls) == 1


class _Response:
    def __init__(self, status: int, body: bytes = b"{}") -> None:
        self.status_code, self._body = status, body

    def iter_content(self, _chunk: int) -> Any:
        yield self._body

    def close(self) -> None:
        pass


class _Egress:
    def __init__(self, status: int) -> None:
        self.status = status
        self.seen: dict[str, Any] = {}

    def get(self, url: str, **kw: Any) -> _Response:
        self.seen = {"url": url, **kw}
        return _Response(self.status, b'{"results": []}')


def test_transport_sends_the_token_as_a_header_to_tmdb_only() -> None:
    egress = _Egress(200)
    EgressTransport(egress, lambda: "secret-token")("/search/movie", {"query": "a b"})  # type: ignore[arg-type]
    assert egress.seen["url"] == "https://api.themoviedb.org/3/search/movie?query=a+b"  # never in the URL
    assert egress.seen["headers"]["Authorization"] == "Bearer secret-token"
    assert egress.seen["host_allowlist"] == frozenset({"api.themoviedb.org"})

    with pytest.raises(TmdbUnavailableError):
        EgressTransport(_Egress(401), lambda: "bad")("/x", {})  # type: ignore[arg-type]
    with pytest.raises(TmdbNotConfiguredError):
        EgressTransport(_Egress(200), lambda: None)("/x", {})  # type: ignore[arg-type]
