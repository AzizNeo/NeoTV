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
    assert kids.code == "TITLE_INVALID" and "rated adult" in kids.body["error"]["details"][0]
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
