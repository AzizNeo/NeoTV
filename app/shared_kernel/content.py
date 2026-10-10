"""Content reference value object.

Every playable/listable item in the system is addressed as
``<namespace>:<id>`` (``catalog:12``, ``live:3``). The namespace names the
module that owns the content; consumers (library, playback, recommendations)
never need to know the owner's tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAMESPACE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class InvalidContentRefError(ValueError):
    pass


@dataclass(frozen=True, slots=True, order=True)
class ContentRef:
    namespace: str
    id: int

    def __post_init__(self) -> None:
        if not _NAMESPACE.fullmatch(self.namespace):
            raise InvalidContentRefError(f"invalid namespace {self.namespace!r}")
        if not isinstance(self.id, int) or isinstance(self.id, bool) or self.id <= 0:
            raise InvalidContentRefError(f"invalid id {self.id!r}")

    @classmethod
    def parse(cls, raw: str) -> ContentRef:
        if not isinstance(raw, str):
            raise InvalidContentRefError("content ref must be a string")
        namespace, sep, ident = raw.partition(":")
        if not sep or not ident.isdigit():
            raise InvalidContentRefError(f"malformed content ref {raw!r}; expected '<namespace>:<id>'")
        return cls(namespace, int(ident))

    def __str__(self) -> str:
        return f"{self.namespace}:{self.id}"
