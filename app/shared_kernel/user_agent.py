"""Small, dependency-free User-Agent classifier (pure functions) shared by devices (inventory) and drm (device-class policy)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedAgent:
    device_type: str
    browser: str
    os: str

    @property
    def display_name(self) -> str:
        return f"{self.browser} on {self.os}"


def _device_type(ua: str) -> str:
    if any(k in ua for k in ("smart-tv", "smarttv", "webos", "tizen", "hbbtv", "appletv", "android tv", "crkey")):
        return "tv"
    if "ipad" in ua or ("android" in ua and "mobile" not in ua) or "tablet" in ua:
        return "tablet"
    if "mobile" in ua or "iphone" in ua:
        return "mobile"
    return "desktop" if ua else "unknown"


def _browser(ua: str) -> str:
    if "edg/" in ua:
        return "Edge"
    if "opr/" in ua or "opera" in ua:
        return "Opera"
    if "firefox" in ua or "fxios" in ua:
        return "Firefox"
    if "chrome" in ua or "crios" in ua:
        return "Chrome"
    if "safari" in ua:
        return "Safari"
    return "Unknown"


def _os(ua: str) -> str:
    if "windows" in ua:
        return "Windows"
    if "iphone" in ua or "ipad" in ua or "ios" in ua:
        return "iOS"
    if "mac os" in ua or "macintosh" in ua:
        return "macOS"
    if "android" in ua:
        return "Android"
    if "linux" in ua or "x11" in ua:
        return "Linux"
    return "Unknown"


def parse_user_agent(user_agent: str | None) -> ParsedAgent:
    ua = (user_agent or "").lower()
    return ParsedAgent(device_type=_device_type(ua), browser=_browser(ua), os=_os(ua))
