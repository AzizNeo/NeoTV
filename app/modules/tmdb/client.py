"""TMDB API v3 over the platform's egress gateway (SSRF rules, timeouts) — read-only, cached.

Only ``api.themoviedb.org`` may be called (host allow-list). Authentication is the v4 "API Read
Access Token" as a bearer header, so the secret never appears in a URL or a log line.
Answers are cached in Redis for a day (TMDB asks clients to cache; metadata changes slowly);
the cache is best effort — Redis down means a live call, never an error.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlencode

from app.kernel.resilience.best_effort import best_effort
from app.kernel.security.egress import EgressDeniedError, EgressGateway, EgressNetworkError
from app.modules.titles.api import TitleKind
from app.modules.tmdb.domain import (
    BACKDROP_SIZE,
    LANGUAGES,
    POSTER_SIZE,
    STILL_SIZE,
    EpisodeMeta,
    GenreMeta,
    SearchHit,
    SeasonMeta,
    Text,
    TitleMeta,
    TmdbNotConfiguredError,
    TmdbNotFoundError,
    TmdbUnavailableError,
    image,
    year_of,
)

API = "https://api.themoviedb.org/3"
HOSTS = frozenset({"api.themoviedb.org"})
CACHE_TTL_S = 24 * 3600
MAX_BODY = 4 * 1024 * 1024
MAX_SEASONS_FETCHED = 30  # a long-running soap must not turn one click into hundreds of calls
_PATH = {TitleKind.MOVIE: "movie", TitleKind.SERIES: "tv"}


class Transport(Protocol):
    """``GET path?params`` → parsed JSON. Production: :class:`EgressTransport`; tests: a fake."""

    def __call__(self, path: str, params: Mapping[str, str]) -> dict[str, Any]: ...


class EgressTransport:
    def __init__(self, egress: EgressGateway, token: Callable[[], str | None]) -> None:
        self._egress = egress
        self._token = token

    def __call__(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        token = self._token()
        if not token:
            raise TmdbNotConfiguredError("TMDB_READ_TOKEN is not set")
        url = f"{API}{path}?{urlencode(sorted(params.items()))}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            response = self._egress.get(url, stream=True, headers=headers, host_allowlist=HOSTS)
        except (EgressNetworkError, EgressDeniedError) as exc:
            raise TmdbUnavailableError("TMDB could not be reached", details={"reason": type(exc).__name__}) from exc
        status = response.status_code
        body = EgressGateway.read_capped(response, MAX_BODY)
        if status == 404:
            raise TmdbNotFoundError("Not found on TMDB")
        if status in (401, 403):
            raise TmdbUnavailableError("TMDB rejected the token", details={"status": status})
        if status != 200:
            raise TmdbUnavailableError("TMDB answered with an error", details={"status": status})
        parsed: dict[str, Any] = json.loads(body)
        return parsed


class TmdbClient:
    def __init__(self, transport: Transport, redis: Any | None = None) -> None:
        self._get = transport
        self._redis = redis

    # ── raw, cached ─────────────────────────────────────────────────────────
    def _cached(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        key = "tmdb:" + hashlib.sha256(f"{path}?{sorted(params.items())}".encode()).hexdigest()[:32]
        redis = self._redis
        if redis is not None:
            hit = best_effort(lambda: redis.get(key), op="tmdb.cache_get")
            if hit:
                cached: dict[str, Any] = json.loads(hit)
                return cached
        data = self._get(path, params)
        if redis is not None:
            best_effort(lambda: redis.set(key, json.dumps(data), ex=CACHE_TTL_S), op="tmdb.cache_set")
        return data

    # ── search ──────────────────────────────────────────────────────────────
    def search(self, query: str, kind: TitleKind, *, year: int | None, locale: str) -> list[SearchHit]:
        params = {"query": query, "language": LANGUAGES[locale], "include_adult": "false", "page": "1"}
        if year:
            params["year" if kind is TitleKind.MOVIE else "first_air_date_year"] = str(year)
        data = self._cached(f"/search/{_PATH[kind]}", params)
        name, original, date = ("title", "original_title", "release_date") if kind is TitleKind.MOVIE else (
            "name", "original_name", "first_air_date"
        )  # fmt: skip
        return [
            SearchHit(
                tmdb_id=int(r["id"]),
                kind=kind,
                name=r.get(name) or r.get(original) or "",
                original_name=r.get(original) or "",
                year=year_of(r.get(date)),
                overview=r.get("overview") or None,
                poster_url=image(r.get("poster_path"), POSTER_SIZE),
            )
            for r in data.get("results", [])[:20]
        ]

    # ── details in every language ───────────────────────────────────────────
    def details(self, tmdb_id: int, kind: TitleKind) -> TitleMeta:
        per_locale = {
            loc: self._cached(f"/{_PATH[kind]}/{tmdb_id}", {"language": lang}) for loc, lang in LANGUAGES.items()
        }
        first = next(iter(per_locale.values()))
        name_key = "title" if kind is TitleKind.MOVIE else "name"
        texts = {
            loc: Text(name=d.get(name_key) or "", synopsis=d.get("overview") or None) for loc, d in per_locale.items()
        }
        genres: dict[int, dict[str, str]] = {}
        for loc, d in per_locale.items():
            for g in d.get("genres", []):
                genres.setdefault(int(g["id"]), {})[loc] = g["name"]
        if kind is TitleKind.MOVIE:
            runtime = first.get("runtime") or None
            date = first.get("release_date")
            seasons: tuple[SeasonMeta, ...] = ()
        else:
            runtime = None
            date = first.get("first_air_date")
            numbers = [int(s["season_number"]) for s in first.get("seasons", []) if int(s["season_number"]) >= 1]
            seasons = tuple(self._season(tmdb_id, n) for n in numbers[:MAX_SEASONS_FETCHED])
        return TitleMeta(
            tmdb_id=tmdb_id,
            kind=kind,
            texts=texts,
            year=year_of(date),
            runtime_minutes=runtime,
            poster_url=image(first.get("poster_path"), POSTER_SIZE),
            backdrop_url=image(first.get("backdrop_path"), BACKDROP_SIZE),
            genres=tuple(GenreMeta(tmdb_id=i, names=n) for i, n in genres.items()),
            seasons=seasons,
        )

    def _season(self, tmdb_id: int, number: int) -> SeasonMeta:
        per_locale = {
            loc: self._cached(f"/tv/{tmdb_id}/season/{number}", {"language": lang}) for loc, lang in LANGUAGES.items()
        }
        episodes: dict[int, dict[str, Any]] = {}
        texts: dict[int, dict[str, Text]] = {}
        for loc, d in per_locale.items():
            for e in d.get("episodes", []):
                n = int(e["episode_number"])
                episodes.setdefault(n, e)
                if e.get("name"):
                    texts.setdefault(n, {})[loc] = Text(name=e["name"], synopsis=e.get("overview") or None)
        return SeasonMeta(
            number=number,
            names={loc: d["name"] for loc, d in per_locale.items() if d.get("name")},
            episodes=tuple(
                EpisodeMeta(
                    number=n,
                    texts=texts.get(n, {}),
                    runtime_minutes=e.get("runtime") or None,
                    still_url=image(e.get("still_path"), STILL_SIZE),
                )
                for n, e in sorted(episodes.items())
            ),
        )
