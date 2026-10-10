"""PUBLIC surface of the _template module (capability ``_template.read``)."""

from __future__ import annotations

from typing import Protocol


class TemplateReader(Protocol):
    def count_for(self, user_id: int) -> int: ...


__all__ = ["TemplateReader"]
