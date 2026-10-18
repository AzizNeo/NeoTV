"""What an Xtream app lists: other modules' catalogues mapped to the protocol's shapes.

Read through capabilities only (``catalog.read``, optional ``live.read``), with the profile's kids
filter applied by the owning module — the same rule as the web storefront.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.kernel.db import dialect_insert
from app.kernel.uow import UnitOfWorkFactory
from app.modules.catalog.api import CatalogReader
from app.modules.live.api import LiveReader
from app.modules.xtream import protocol
from app.modules.xtream.domain import XtreamPrincipal
from app.modules.xtream.models import XtreamCategory

ADULT = "adult"


class XtreamCatalog:
    def __init__(self, uow: UnitOfWorkFactory, catalog: CatalogReader, live: LiveReader | None) -> None:
        self._uow = uow
        self._catalog = catalog
        self._live = live

    # ── live ──────────────────────────────────────────────────────────────

    def live_categories(self, who: XtreamPrincipal) -> list[dict[str, Any]]:
        names = self._live_category_names(who)
        ids = self.category_ids("live", names)
        return [protocol.category(ids[name], name) for name in names]

    def live_streams(self, who: XtreamPrincipal, *, category_id: str | None = None) -> list[dict[str, Any]]:
        channels = self._catalog.listing(kind="live", kids_only=who.is_kids)
        own = self._live.listing(kids_only=who.is_kids) if self._live is not None else []
        ids = self.category_ids("live", self._live_category_names(who, channels=channels, own=own))
        rows: list[dict[str, Any]] = [
            {
                "ref": c.ref,
                "name": c.name,
                "icon": c.logo,
                "category_id": ids[c.group],
                "epg_channel_id": None,
                "added_at": c.added_at,
                "adult": c.rating == ADULT,
            }
            for c in channels
        ]
        rows += [
            {
                "ref": o.ref,
                "name": o.name,
                "icon": o.logo,
                "category_id": ids[protocol.OWN_LIVE_CATEGORY],
                "epg_channel_id": o.epg_channel_id,
                "added_at": o.added_at,
                "adult": o.rating == ADULT,
            }
            for o in own
        ]
        if category_id is not None:
            rows = [r for r in rows if str(r["category_id"]) == category_id]
        return [protocol.live_stream(num=n, **row) for n, row in enumerate(rows, start=1)]

    # ── categories ────────────────────────────────────────────────────────

    def category_ids(self, section: str, names: list[str]) -> dict[str, int]:
        """Stable numeric id per name, created the first time a name is listed."""
        if not names:
            return {}
        table = XtreamCategory.__table__
        with self._uow() as uow:
            known = self._known(uow.session, section, names)
            missing = [n for n in dict.fromkeys(names) if n not in known]
            if missing:
                uow.session.execute(
                    dialect_insert(uow.session, table)
                    .values([{"section": section, "name": n} for n in missing])
                    .on_conflict_do_nothing(index_elements=["section", "name"])  # a parallel request won the race
                )
                known = self._known(uow.session, section, names)
            return known

    @staticmethod
    def _known(session: Any, section: str, names: list[str]) -> dict[str, int]:
        rows = session.execute(
            select(XtreamCategory.name, XtreamCategory.id).where(
                XtreamCategory.section == section, XtreamCategory.name.in_(names)
            )
        )
        return {name: int(cid) for name, cid in rows}

    def _live_category_names(self, who: XtreamPrincipal, *, channels: Any = None, own: Any = None) -> list[str]:
        if channels is None:
            channels = self._catalog.listing(kind="live", kids_only=who.is_kids)
        if own is None:
            own = self._live.listing(kids_only=who.is_kids) if self._live is not None else []
        names = list(dict.fromkeys(c.group for c in channels))
        if own:
            names.append(protocol.OWN_LIVE_CATEGORY)
        return names
