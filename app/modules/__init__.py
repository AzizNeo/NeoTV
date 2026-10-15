"""Installed modules (puzzle pieces).

Order is irrelevant — the kernel registry derives the boot order from each
manifest's ``requires``. Adding a module = one line here. Disabling one
temporarily = ``DISABLED_MODULES=<name>`` (the registry refuses to boot, with
a named error, if another enabled module *requires* it).
"""

from __future__ import annotations

INSTALLED_MODULES: tuple[str, ...] = (
    "app.modules.identity",
    "app.modules.notifications",
    "app.modules.profile",
    "app.modules.devices",
    "app.modules.catalog",
    "app.modules.titles",
    "app.modules.tmdb",
    "app.modules.live",
    "app.modules.billing",
    "app.modules.playback",
    "app.modules.drm",
    "app.modules.library",
    "app.modules.recommendations",
    "app.modules.admin",
)
