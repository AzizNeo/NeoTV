"""Content rating rules shared by every listing and by the playback gate.

One function, one truth: a kids profile can *see* exactly what it can *play*.
"""

from __future__ import annotations

RATINGS: tuple[str, ...] = ("general", "teen", "adult", "unrated")
KIDS_ALLOWED: frozenset[str] = frozenset({"general"})


def allowed_for_kids(rating: str) -> bool:
    return rating in KIDS_ALLOWED
