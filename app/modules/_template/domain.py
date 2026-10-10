"""Pure rules and named errors of the _template module."""

from __future__ import annotations

MAX_TITLE = 120


class TemplateItemNotFoundError(LookupError):
    pass


def normalise_title(raw: str) -> str:
    title = " ".join(raw.split())
    if not title:
        raise ValueError("title must not be blank")
    return title[:MAX_TITLE]
