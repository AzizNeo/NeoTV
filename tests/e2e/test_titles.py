"""titles end to end: the admin document API over real catalog sources."""

from __future__ import annotations

from typing import Any

from tests.support.client import Api

ADMIN = "/api/v1/titles/admin/titles"


def _movie(ref: str, **kw: Any) -> dict[str, Any]:
    return {
        "kind": "movie",
        "name": "Sintel",
        "play_ref": ref,
        "year": 2010,
        "genres": ["Animasyon", "Fantastik"],
        **kw,
    }


def test_title_documents_round_trip_and_replace_whole(api: Api) -> None:
    admin = api.user("boss", role="admin")
    a = api.channel(admin, "Ep One", group="Shorts")
    b = api.channel(admin, "Ep Two", group="Shorts")
    series = {
        "kind": "series",
        "name": "Open Shorts",
        "rating": "general",
        "genres": ["Animasyon"],
        "seasons": [
            {"number": 1, "episodes": [{"number": 1, "name": "One", "play_ref": f"catalog:{a['id']}"}]},
            {"number": 2, "episodes": [{"number": 1, "name": "Two", "play_ref": f"catalog:{b['id']}"}]},
        ],
    }
    created = api.put(f"{ADMIN}/open-shorts", token=admin, json=series)
    assert created.status == 201, created.body
    assert created.data["slug"] == "open-shorts" and len(created.data["seasons"]) == 2

    series["seasons"] = series["seasons"][1:]  # PUT replaces the aggregate: season 1 disappears
    replaced = api.put(f"{ADMIN}/open-shorts", token=admin, json=series)
    assert replaced.status == 200 and [s["number"] for s in replaced.data["seasons"]] == [2]
    assert api.get(f"{ADMIN}/open-shorts", token=admin).data == replaced.data  # lossless round trip

    assert api.delete(f"{ADMIN}/open-shorts", token=admin).status == 204
    assert api.get(f"{ADMIN}/open-shorts", token=admin).code == "TITLE_NOT_FOUND"
    assert api.get(f"/api/v1/catalog/channels/{a['id']}", token=admin).status == 200  # sources untouched


def test_sources_are_checked_and_kids_rule_holds(api: Api) -> None:
    admin = api.user("boss", role="admin")
    adult = api.channel(admin, "Late Film", rating="adult")
    live = api.channel(admin, "News 24", kind="live")

    missing = api.put(f"{ADMIN}/ghost", token=admin, json=_movie("catalog:999"))
    assert missing.code == "PLAY_SOURCE_NOT_FOUND" and missing.body["error"]["details"] == ["catalog:999"]
    assert api.put(f"{ADMIN}/news", token=admin, json=_movie(f"catalog:{live['id']}")).code == "TITLE_INVALID"
    kids = api.put(f"{ADMIN}/late", token=admin, json=_movie(f"catalog:{adult['id']}", rating="general"))
    assert kids.code == "TITLE_RATING_CONFLICT"
    assert kids.body["error"]["details"] == [f"play_ref 'catalog:{adult['id']}': rated adult"]
    assert api.put(f"{ADMIN}/late", token=admin, json=_movie(f"catalog:{adult['id']}", rating="adult")).status == 201

    invalid = api.put(
        f"{ADMIN}/Bad Slug", token=admin, json=_movie(f"catalog:{adult['id']}", rating="adult", year=1700)
    )
    assert invalid.code == "TITLE_INVALID"
    assert [d.split(":")[0] for d in invalid.body["error"]["details"]] == ["slug", "year"]  # all problems at once


def test_admin_list_reports_unavailable_sources_and_heals(api: Api) -> None:
    admin = api.user("boss", role="admin")
    source = api.channel(admin, "Tears")
    assert api.put(f"{ADMIN}/tears", token=admin, json=_movie(f"catalog:{source['id']}", name="Tears")).status == 201
    [row] = api.get(ADMIN, token=admin).data["items"]
    assert (row["sources"], row["unavailable_sources"]) == (1, 0)

    api.delete(f"/api/v1/catalog/admin/channels/{source['id']}", token=admin)
    [row] = api.get(ADMIN, token=admin).data["items"]
    assert row["unavailable_sources"] == 1  # link kept, flagged — not silently erased
    assert api.get(f"{ADMIN}/tears", token=admin).data["play_ref"] == f"catalog:{source['id']}"


def test_title_admin_requires_permission(api: Api) -> None:
    viewer = api.user("viewer")
    assert api.get(ADMIN, token=viewer).code == "PERMISSION_DENIED"
    assert api.put(f"{ADMIN}/x", token=viewer, json=_movie("catalog:1")).code == "PERMISSION_DENIED"


# ── viewer API ───────────────────────────────────────────────────────────────
BROWSE = "/api/v1/titles"


def _shelf(api: Api, admin: str) -> dict[str, dict[str, Any]]:
    """Two kids-safe titles, one adult title, one unpublished draft."""
    src = {
        n: api.channel(admin, n, rating=r)
        for n, r in (("Bunny", "general"), ("E1", "general"), ("E2", "general"), ("Night", "adult"))
    }
    docs = {
        "bunny": _movie(f"catalog:{src['Bunny']['id']}", name="Bunny", rating="general", year=2008, genres=["Animasyon", "Komedi"], featured_rank=2),
        "night": _movie(f"catalog:{src['Night']['id']}", name="Night Shift", rating="adult", year=2020, genres=["Gerilim"], featured_rank=1),
        "shorts": {
            "kind": "series", "name": "Shorts", "rating": "general", "year": 2015, "genres": ["Animasyon"],
            "seasons": [{"number": 1, "episodes": [
                {"number": 1, "name": "One", "play_ref": f"catalog:{src['E1']['id']}"},
                {"number": 2, "name": "Two", "play_ref": f"catalog:{src['E2']['id']}"},
            ]}],
        },
        "draft": _movie(None, name="Draft", is_published=False),  # type: ignore[arg-type]
    }  # fmt: skip
    for slug, doc in docs.items():
        assert api.put(f"{ADMIN}/{slug}", token=admin, json=doc).status == 201, slug
    return src


def _kids_header(api: Api, viewer: str) -> dict[str, str]:
    api.post("/api/v1/billing/trial", token=viewer)
    kid = api.post("/api/v1/profiles", token=viewer, json={"name": "Kid", "is_kids": True}).data
    token = api.post(f"/api/v1/profiles/{kid['id']}/select", token=viewer, json={}).data["profile_token"]
    return {"X-Profile-Token": token}


def test_browse_filters_search_and_sort(api: Api, admin: str, viewer: str) -> None:
    _shelf(api, admin)
    page = api.get(BROWSE, token=viewer, query_string={"sort": "name"}).data
    assert [t["slug"] for t in page["items"]] == ["bunny", "night", "shorts"] and page["total"] == 3  # no draft
    assert all(t["available"] for t in page["items"])

    def slugs(**q: Any) -> list[str]:
        return [t["slug"] for t in api.get(BROWSE, token=viewer, query_string=q).data["items"]]

    assert slugs(genre="animasyon", sort="name") == ["bunny", "shorts"]
    assert slugs(kind="series") == ["shorts"]
    assert slugs(search="SHIFT") == ["night"]
    assert slugs(search="%") == []  # LIKE wildcards are literal
    assert slugs(year_from=2010, sort="year") == ["night", "shorts"]

    genres = api.get(f"{BROWSE}/genres", token=viewer).data
    assert genres[0] == {"slug": "animasyon", "name": "Animasyon", "count": 2}
    rails = api.get(f"{BROWSE}/rails", token=viewer, query_string={"genres": 1}).data
    assert [t["slug"] for t in rails[0]["items"]] == ["bunny", "shorts"]  # featured first


def test_detail_featured_and_availability_follow_sources(api: Api, admin: str, viewer: str) -> None:
    src = _shelf(api, admin)
    shorts = api.get(f"{BROWSE}/shorts", token=viewer).data
    assert shorts["card"]["season_count"] == 1 and len(shorts["seasons"][0]["episodes"]) == 2
    assert shorts["genre_links"] == [{"slug": "animasyon", "name": "Animasyon"}]
    assert api.get(f"{BROWSE}/draft", token=viewer).code == "TITLE_NOT_FOUND"  # unpublished: invisible

    hero = api.get(f"{BROWSE}/featured", token=viewer).data
    assert [h["card"]["slug"] for h in hero] == ["night", "bunny"]
    assert hero[1]["play_ref"] == f"catalog:{src['Bunny']['id']}"

    api.delete(f"/api/v1/catalog/admin/channels/{src['Bunny']['id']}", token=admin)
    api.delete(f"/api/v1/catalog/admin/channels/{src['E1']['id']}", token=admin)
    assert [h["card"]["slug"] for h in api.get(f"{BROWSE}/featured", token=viewer).data] == ["night"]
    listing = {t["slug"]: t["available"] for t in api.get(BROWSE, token=viewer).data["items"]}
    assert listing == {"bunny": False, "night": True, "shorts": True}  # flagged, not hidden
    episodes = api.get(f"{BROWSE}/shorts", token=viewer).data["seasons"][0]["episodes"]
    assert [e["available"] for e in episodes] == [False, True]


def test_kids_profile_sees_only_what_it_may_play(api: Api, admin: str, viewer: str) -> None:
    _shelf(api, admin)
    kids = _kids_header(api, viewer)
    assert {t["slug"] for t in api.get(BROWSE, token=viewer, headers=kids).data["items"]} == {"bunny", "shorts"}
    assert api.get(f"{BROWSE}/night", token=viewer, headers=kids).code == "TITLE_NOT_FOUND"
    assert [h["card"]["slug"] for h in api.get(f"{BROWSE}/featured", token=viewer, headers=kids).data] == ["bunny"]
    assert "gerilim" not in {g["slug"] for g in api.get(f"{BROWSE}/genres", token=viewer, headers=kids).data}
