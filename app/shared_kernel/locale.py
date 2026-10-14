"""Interface languages shared by every module (the frontend has the same list: core/i18n/locale.js)."""

from __future__ import annotations

SUPPORTED_LOCALES: tuple[str, ...] = ("tr", "en")
DEFAULT_LOCALE = "tr"


def supported(locale: str | None) -> str | None:
    """``"en-US"`` → ``"en"``; ``None`` for anything we do not speak."""
    if not locale:
        return None
    base = locale.strip().lower().replace("_", "-").split("-")[0]
    return base if base in SUPPORTED_LOCALES else None


def negotiate(accept_language: str | None) -> str | None:
    """Best supported language of an ``Accept-Language`` header (q-values honoured), or ``None``.

    ``"de-DE,en;q=0.8,tr;q=0.9"`` → ``"tr"``. Malformed parts are skipped, never fatal.
    """
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate((accept_language or "").split(",")[:20]):
        tag, _, params = part.strip().partition(";")
        weight = 1.0
        if params.strip().startswith("q="):
            try:
                weight = float(params.strip()[2:])
            except ValueError:
                continue
        locale = supported(tag)
        if locale and weight > 0:
            ranked.append((-weight, position, locale))
    return min(ranked)[2] if ranked else None
