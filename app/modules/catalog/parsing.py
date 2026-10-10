"""Pure M3U / plain-link parsing (no I/O, fully unit-testable)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_ATTR = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')
_HTTP = ("http://", "https://")
_VOD_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v")
_ADULT_HINTS = ("adult", "xxx", "18+", "+18", "yetiskin", "yetişkin", "erotic")
_KIDS_HINTS = ("kids", "çocuk", "cocuk", "cartoon", "çizgi", "cizgi", "children")


@dataclass(frozen=True, slots=True)
class ParsedEntry:
    name: str
    url: str
    logo: str | None = None
    group: str | None = None
    tvg_id: str | None = None

    @property
    def source_key(self) -> str:
        if self.tvg_id:
            return f"tvg:{self.tvg_id[:70]}"
        return "url:" + hashlib.sha1(self.url.strip().encode(), usedforsecurity=False).hexdigest()

    @property
    def kind_hint(self) -> str | None:
        lowered = self.url.lower().split("?", 1)[0]
        if lowered.endswith(_VOD_EXTENSIONS):
            return "vod"
        group = (self.group or "").lower()
        if any(k in group for k in ("movie", "film", "sinema", "vod", "dizi", "series")):
            return "vod"
        return None

    @property
    def rating_hint(self) -> str:
        haystack = f"{self.group or ''} {self.name}".lower()
        if any(k in haystack for k in _ADULT_HINTS):
            return "adult"
        if any(k in haystack for k in _KIDS_HINTS):
            return "general"
        return "unrated"


def parse_text(text: str) -> list[ParsedEntry]:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    return _parse_m3u(text) if "#EXTINF" in text.upper() else _parse_plain(text)


def _parse_m3u(content: str) -> list[ParsedEntry]:
    entries: list[ParsedEntry] = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line.upper().startswith("#EXTINF"):
            continue
        attrs = {k.lower(): v.strip() for k, v in _ATTR.findall(line)}
        display = line.rsplit(",", 1)[-1].strip() if "," in line else ""
        url = None
        while i < len(lines):
            candidate = lines[i].strip()
            i += 1
            if not candidate or candidate.startswith("#"):
                continue
            url = candidate
            break
        if not url or not url.startswith(_HTTP):
            continue
        entries.append(
            ParsedEntry(
                name=(attrs.get("tvg-name") or display or "Unknown Channel")[:256],
                url=url[:1024],
                logo=(attrs.get("tvg-logo") or None),
                group=(attrs.get("group-title") or None),
                tvg_id=(attrs.get("tvg-id") or None),
            )
        )
    return _dedupe(entries)


def _parse_plain(text: str) -> list[ParsedEntry]:
    entries: list[ParsedEntry] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[1].startswith(_HTTP):
            entries.append(
                ParsedEntry(
                    name=parts[0][:256] or "Unknown",
                    url=parts[1][:1024],
                    logo=parts[2] if len(parts) > 2 and parts[2] else None,
                )
            )
        elif line.startswith(_HTTP):
            stem = line.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            name = re.sub(r"\.(m3u8?|ts|mp4)$", "", stem, flags=re.I).replace("_", " ").title() or "Stream"
            entries.append(ParsedEntry(name=name[:256], url=line[:1024]))
    return _dedupe(entries)


def _dedupe(entries: list[ParsedEntry]) -> list[ParsedEntry]:
    seen: set[str] = set()
    unique: list[ParsedEntry] = []
    for entry in entries:
        if entry.source_key in seen:
            continue
        seen.add(entry.source_key)
        unique.append(entry)
    return unique
