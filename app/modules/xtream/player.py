"""xtream HTTP adapter, app side: the Xtream Codes routes TV apps call.

Apps call ``<server>/player_api.php``; nginx maps the protocol's root paths onto
``/api/v1/xtream/…``, where every route stays behind ``endpoint()`` like the rest of the API. Answers are the
protocol's bare JSON — not NeoTV's ``{success, data}`` envelope — and are never cached: they are
per account and per profile.

Credentials arrive as ``username``/``password`` in the query string or a form body (apps do both).
They are app credentials (ADR-0011), checked on every request; any failure gets the protocol's
one "not authorised" answer.
"""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, Response, request

from app.kernel.capabilities import CapabilityIndex
from app.kernel.container import resolve
from app.kernel.http.endpoint import endpoint
from app.kernel.resilience.rate_limit import Rate
from app.kernel.time import Clock
from app.modules.xtream import protocol
from app.modules.xtream.catalog import XtreamCatalog
from app.modules.xtream.domain import XtreamPrincipal
from app.modules.xtream.services import CredentialService

blueprint = Blueprint("xtream_player", __name__)
_TAGS = ("xtream",)
# An app loads a few lists at start-up, then mostly streams; per address, as the caller is not
# known before its credential is checked.
_RATE = Rate("xtream.player_api", rps=5, burst=40, per="ip")
# Whole-catalogue exports: apps fetch them at start-up and then every few hours.
_EXPORT_RATE = Rate("xtream.export", rps=0.2, burst=6, per="ip")
_EPG_LIMIT_DEFAULT = 4
_EPG_LIMIT_MAX = 50


def _answer(payload: Any, *, status: int = 200) -> Response:
    response = Response(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), status=status)
    response.mimetype = "application/json"
    response.headers["Cache-Control"] = "no-store"
    return response


def _principal() -> XtreamPrincipal | None:
    values = request.values  # query string and form body
    return resolve(CredentialService).authenticate(values.get("username", ""), values.get("password", ""))


def _entitled_streams(user_id: int) -> int:
    entitlements = resolve(CapabilityIndex).optional("billing.entitlements")
    return int(entitlements.for_user(user_id).max_streams) if entitlements is not None else 1


@blueprint.route("/player_api.php", methods=["GET", "POST"])
@endpoint(
    auth="public",
    summary="Xtream Codes player API (app credentials; ?action=… selects the list)",
    tags=_TAGS,
    rate=_RATE,
)
def player_api() -> Response:
    who = _principal()
    action = request.values.get("action", "")
    if who is None:
        # The login probe (no action) expects 200 + auth 0; data requests are refused outright.
        return _answer(protocol.DENIED, status=200 if not action else 401)
    catalog = resolve(XtreamCatalog)
    if not action:
        account = protocol.Account(
            username=who.username,
            password=request.values.get("password", ""),
            created_at=who.created_at,
            max_connections=_entitled_streams(who.user_id),
            active_connections=0,
        )
        return _answer(
            protocol.login(account, server_url=resolve(CredentialService).server_url, now=resolve(Clock).now())
        )
    if action == "get_live_categories":
        return _answer(catalog.live_categories(who))
    if action == "get_live_streams":
        return _answer(catalog.live_streams(who, category_id=request.values.get("category_id") or None))
    if action == "get_short_epg":
        limit = request.values.get("limit", "")
        count = min(int(limit), _EPG_LIMIT_MAX) if limit.isdigit() and int(limit) > 0 else _EPG_LIMIT_DEFAULT
        return _answer(
            catalog.short_epg(who, request.values.get("stream_id", ""), limit=count, now=resolve(Clock).now())
        )
    if action == "get_simple_data_table":
        return _answer(catalog.simple_data_table(who, request.values.get("stream_id", ""), now=resolve(Clock).now()))
    return _titles(catalog, who, action)


def _titles(catalog: XtreamCatalog, who: XtreamPrincipal, action: str) -> Response:
    category = request.values.get("category_id") or None
    if action == "get_vod_categories":
        return _answer(catalog.vod_categories(who))
    if action == "get_vod_streams":
        return _answer(catalog.vod_streams(who, category_id=category))
    if action == "get_vod_info":
        info = catalog.vod_info(who, request.values.get("vod_id", ""))
        return _answer(info) if info is not None else _answer([], status=404)
    if action == "get_series_categories":
        return _answer(catalog.series_categories(who))
    if action == "get_series":
        return _answer(catalog.series(who, category_id=category))
    if action == "get_series_info":
        details = catalog.series_info(who, request.values.get("series_id", ""))
        return _answer(details) if details is not None else _answer([], status=404)
    return _answer([])  # unknown actions: an empty list, as Xtream servers answer


@blueprint.get("/xmltv.php")
@endpoint(
    auth="public",
    summary="Xtream Codes XMLTV guide for the credential's channels",
    tags=_TAGS,
    rate=_EXPORT_RATE,
)
def xmltv() -> Response:
    who = _principal()
    if who is None:
        return _refused()
    body = resolve(XtreamCatalog).guide(who, now=resolve(Clock).now())
    return _file(body, "application/xml; charset=utf-8", "neotv.xml")


@blueprint.get("/get.php")
@endpoint(
    auth="public",
    summary="Xtream Codes M3U playlist of everything the credential can play (HLS URLs)",
    tags=_TAGS,
    rate=_EXPORT_RATE,
)
def playlist() -> Response:
    who = _principal()
    if who is None:
        return _refused()
    text = protocol.m3u(
        resolve(XtreamCatalog).playlist(who),
        server_url=resolve(CredentialService).server_url,
        username=who.username,
        password=request.values.get("password", ""),
    )
    return _file(text.encode(), "audio/x-mpegurl; charset=utf-8", "neotv.m3u")


def _refused() -> Response:
    response = Response(b"", status=401)
    response.headers["Cache-Control"] = "no-store"
    return response


def _file(body: bytes, content_type: str, filename: str) -> Response:
    response = Response(body, status=200, content_type=content_type)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response
