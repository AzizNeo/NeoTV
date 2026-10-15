"""A fake TMDB (API v3 response shapes, trimmed) — tests never call the network.

Texts are written for these tests; ids are arbitrary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.tmdb.domain import TmdbNotFoundError

MOVIE_ID, SHOW_ID = 45745, 9001

_GENRES = {
    "tr-TR": [{"id": 16, "name": "Animasyon"}, {"id": 14, "name": "Fantastik"}],
    "en-US": [{"id": 16, "name": "Animation"}, {"id": 14, "name": "Fantasy"}],
}
_MOVIE = {
    "tr-TR": {"title": "Sintel", "overview": "Bir kız kayıp ejderhasını arar."},
    "en-US": {"title": "Sintel", "overview": "A girl searches for her lost dragon."},
}
_SHOW = {
    "tr-TR": {"name": "Açık Kısalar", "overview": "Kısa filmlerden bir seçki."},
    "en-US": {"name": "Open Shorts", "overview": "A selection of short films."},
}
_EPISODES = {
    "tr-TR": [("Başlangıç", "İlk bölüm."), ("Devam", "İkinci bölüm.")],
    "en-US": [("Beginning", "The first episode."), ("Onward", "The second episode.")],
}


class FakeTmdb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, path: str, params: Mapping[str, str]) -> dict[str, Any]:
        self.calls.append((path, dict(params)))
        lang = params.get("language", "en-US")
        if path == "/search/movie":
            return {"results": [{
                "id": MOVIE_ID, "title": "Sintel", "original_title": "Sintel", "release_date": "2010-09-27",
                "overview": _MOVIE[lang]["overview"], "poster_path": "/sintel.jpg",
            }]}  # fmt: skip
        if path == "/search/tv":
            return {"results": [{
                "id": SHOW_ID, "name": _SHOW[lang]["name"], "original_name": "Open Shorts",
                "first_air_date": "2015-01-01", "overview": None, "poster_path": None,
            }]}  # fmt: skip
        if path == f"/movie/{MOVIE_ID}":
            return {
                "id": MOVIE_ID, **_MOVIE[lang], "runtime": 15, "release_date": "2010-09-27",
                "genres": _GENRES[lang], "poster_path": "/sintel.jpg", "backdrop_path": "/sintel-bg.jpg",
            }  # fmt: skip
        if path == f"/tv/{SHOW_ID}":
            return {
                "id": SHOW_ID, **_SHOW[lang], "first_air_date": "2015-01-01", "genres": _GENRES[lang][:1],
                "poster_path": "/shorts.jpg", "backdrop_path": None,
                "seasons": [{"season_number": 0, "episode_count": 1}, {"season_number": 1, "episode_count": 2}],
            }  # fmt: skip
        if path == f"/tv/{SHOW_ID}/season/1":
            return {
                "name": "1. Sezon" if lang == "tr-TR" else "Season 1",
                "episodes": [
                    {"episode_number": n, "name": name, "overview": about, "runtime": 22, "still_path": f"/s1e{n}.jpg"}
                    for n, (name, about) in enumerate(_EPISODES[lang], start=1)
                ],
            }
        raise TmdbNotFoundError("Not found on TMDB")
