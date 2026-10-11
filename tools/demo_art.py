"""Generate the demo artwork served from ``frontend/public/demo/`` (16:9 SVG).

Original, dependency-free artwork for the demo catalogue — no third-party images,
no hot-linking. Re-run after changing ``ARTWORK``:

    python -m tools.demo_art
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "demo"


@dataclass(frozen=True, slots=True)
class Art:
    slug: str
    title: str
    kicker: str
    top: str  # gradient colours
    bottom: str
    accent: str
    live: bool = False


ARTWORK: tuple[Art, ...] = (
    Art("big-buck-bunny", "Big Buck Bunny", "Open Movie · 2008", "#3a7d44", "#0f2a14", "#f4d35e"),
    Art("sintel", "Sintel", "Open Movie · 2010", "#5b2a86", "#12061f", "#ff7a59"),
    Art("tears-of-steel", "Tears of Steel", "Open Movie · 2012", "#1f4e79", "#060d18", "#5fd3ff"),
    Art("bipbop-basic", "BipBop", "Apple HLS test stream", "#444444", "#0b0b0b", "#e50914"),
    Art("bipbop-advanced", "BipBop Advanced", "Apple HLS test stream · fMP4", "#2b2b40", "#08080f", "#a78bfa"),
    Art("test-streams", "Test Yayınları", "Dizi · HLS test akışları", "#3b3b3b", "#0a0a0a", "#22d3ee"),
    Art("live-akamai", "Akamai Live", "24/7 test channel", "#7a1e1e", "#160505", "#ffffff", live=True),
    Art("live-unified", "Unified Live", "24/7 test channel", "#14532d", "#03140a", "#ffffff", live=True),
)


def render(art: Art) -> str:
    title_size = 120 if len(art.title) <= 10 else 96
    live_badge = (
        '<g transform="translate(80,96)"><rect width="150" height="54" rx="10" fill="#e50914"/>'
        '<circle cx="34" cy="27" r="9" fill="#fff"/>'
        '<text x="56" y="38" font-size="30" font-weight="800" fill="#fff">LIVE</text></g>'
        if art.live
        else ""
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" role="img" aria-label="{escape(art.title)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{art.top}"/><stop offset="1" stop-color="{art.bottom}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.82" cy="0.18" r="0.7">
      <stop offset="0" stop-color="{art.accent}" stop-opacity="0.35"/><stop offset="1" stop-color="{art.accent}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)"/>
  <rect width="1280" height="720" fill="url(#glow)"/>
  <g fill="none" stroke="{art.accent}" stroke-opacity="0.18" stroke-width="2">
    <circle cx="1040" cy="170" r="140"/><circle cx="1040" cy="170" r="220"/><circle cx="1040" cy="170" r="300"/>
  </g>
  {live_badge}
  <g font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif">
    <text x="80" y="560" font-size="{title_size}" font-weight="800" fill="#ffffff" letter-spacing="-2">{escape(art.title)}</text>
    <rect x="80" y="592" width="90" height="8" rx="4" fill="{art.accent}"/>
    <text x="80" y="652" font-size="36" font-weight="500" fill="#ffffff" fill-opacity="0.75">{escape(art.kicker)}</text>
  </g>
</svg>
"""


def render_poster(art: Art) -> str:
    """2:3 poster for cards (``<slug>-poster.svg``); same palette as the 16:9 backdrop."""
    words = escape(art.title).split()
    lines = [" ".join(words[i : i + 2]) for i in range(0, len(words), 2)]  # ≤ 2 words per line
    tspans = "".join(f'<tspan x="60" dy="{0 if i == 0 else 92}">{line}</tspan>' for i, line in enumerate(lines))
    top = 1010 - 92 * (len(lines) - 1)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 1200" role="img" aria-label="{escape(art.title)}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{art.top}"/><stop offset="1" stop-color="{art.bottom}"/>
    </linearGradient>
  </defs>
  <rect width="800" height="1200" fill="url(#bg)"/>
  <g fill="none" stroke="{art.accent}" stroke-opacity="0.22" stroke-width="3">
    <circle cx="400" cy="420" r="150"/><circle cx="400" cy="420" r="240"/><circle cx="400" cy="420" r="330"/>
  </g>
  <circle cx="400" cy="420" r="18" fill="{art.accent}"/>
  <g font-family="Inter, Segoe UI, Helvetica, Arial, sans-serif">
    <text y="{top}" font-size="84" font-weight="800" fill="#ffffff" letter-spacing="-2">{tspans}</text>
    <rect x="60" y="1048" width="80" height="8" rx="4" fill="{art.accent}"/>
    <text x="60" y="1110" font-size="34" font-weight="500" fill="#ffffff" fill-opacity="0.75">{escape(art.kicker)}</text>
  </g>
</svg>
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for art in ARTWORK:
        (OUT / f"{art.slug}.svg").write_text(render(art), encoding="utf-8")
        if not art.live:
            (OUT / f"{art.slug}-poster.svg").write_text(render_poster(art), encoding="utf-8")
    print(f"wrote artwork for {len(ARTWORK)} items to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
