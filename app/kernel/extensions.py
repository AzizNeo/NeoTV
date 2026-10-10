"""Extension points — the "many providers" edge of the puzzle.

A capability (``provides``) has exactly one provider. An *extension point* has
zero-or-more contributors: e.g. ``playback.policies`` collects playback rules
from any module (billing contributes an entitlement rule, catalog a rating
rule, ...). The owner declares the point; contributors reference it; the
kernel validates both sides at boot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.kernel.errors import DuplicateExtensionPointError, UnknownExtensionPointError

_log = logging.getLogger("kernel.extensions")


@dataclass(frozen=True, slots=True)
class Contribution:
    owner: str
    point: str
    factory: Callable[[Any], Any]


class ExtensionRegistry:
    def __init__(self) -> None:
        self._points: dict[str, str] = {}
        self._contributions: dict[str, list[Contribution]] = {}
        self._disabled_points: set[str] = set()

    def declare(self, point: str, owner: str) -> None:
        if point in self._points:
            raise DuplicateExtensionPointError(point, self._points[point], owner)
        self._points[point] = owner
        self._contributions.setdefault(point, [])

    def mark_disabled(self, point: str) -> None:
        """Points declared by a disabled module: contributions are dropped (logged), not errors."""
        self._disabled_points.add(point)

    def contribute(self, point: str, owner: str, factory: Callable[[Any], Any]) -> None:
        if point not in self._points:
            if point in self._disabled_points:
                _log.info("extension.dropped point=%s owner=%s reason=declaring_module_disabled", point, owner)
                return
            raise UnknownExtensionPointError(owner, point)
        self._contributions[point].append(Contribution(owner, point, factory))

    def is_declared(self, point: str) -> bool:
        return point in self._points

    def contributions(self, point: str) -> list[Contribution]:
        if point not in self._points:
            raise UnknownExtensionPointError("<lookup>", point)
        return list(self._contributions[point])

    def build(self, point: str, container: Any) -> list[Any]:
        """Instantiate every contribution with the container (deterministic order: owner, then registration)."""
        built = []
        for contribution in sorted(self.contributions(point), key=lambda c: c.owner):
            built.append(contribution.factory(container))
        return built

    def describe(self) -> dict[str, dict[str, Any]]:
        return {
            point: {"owner": owner, "contributors": sorted({c.owner for c in self._contributions[point]})}
            for point, owner in sorted(self._points.items())
        }
