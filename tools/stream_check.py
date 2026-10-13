"""Can *this server* reach its stream sources? Answers per source, with the reason when not.

    python -m tools.devctl stream-check          every active catalog + external live source
    python -m tools.devctl stream-check URL ...  specific upstream URLs

Uses the application's own EgressGateway — the exact door the HLS proxy uses (same DNS,
public-IP and TLS rules) — so "OK" here means the proxy can fetch it too. Prints the host
only, never full URLs (provider links may embed credentials), so the output is safe to share.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from urllib.parse import urlsplit

_PEEK_BYTES = 4096

HINTS = {
    "dns": "name could not be resolved: check the internet connection / DNS (VPN, Pi-hole, ISP filter)",
    "tls": "TLS handshake failed: antivirus or a corporate proxy may be intercepting HTTPS",
    "timeout": "no answer in time: slow network, firewall, or the source is down",
    "connect": "connection refused/reset: firewall or the source is down",
    "blocked": "blocked by the egress policy (private/reserved address or disallowed port)",
    "body": "connection dropped while reading",
}


@dataclass(frozen=True, slots=True)
class Verdict:
    name: str
    host: str
    ok: bool
    detail: str


def check(gateway: object, name: str, url: str) -> Verdict:
    from app.kernel.security.egress import EgressDeniedError, EgressGateway, EgressNetworkError

    host = urlsplit(url).hostname or "?"
    try:
        response = gateway.get(url, stream=True)  # type: ignore[attr-defined]
    except EgressNetworkError as exc:
        return Verdict(name, host, False, f"{exc.kind}: {HINTS.get(exc.kind, '')}")
    except EgressDeniedError as exc:
        kind = "dns" if exc.reason == "dns" else "blocked"
        extra = "" if exc.reason == kind else f" ({exc.reason})"
        return Verdict(name, host, False, f"{kind}: {HINTS[kind]}{extra}")
    try:
        if response.status_code not in (200, 206):
            return Verdict(name, host, False, f"HTTP {response.status_code} from the source")
        head = EgressGateway.read_capped(response, _PEEK_BYTES * 64)[:_PEEK_BYTES]
    except Exception as exc:  # diagnostic tool: report, never crash
        return Verdict(name, host, False, f"body: {type(exc).__name__}")
    finally:
        response.close()
    is_playlist = head.lstrip().startswith(b"#EXTM3U")
    kind = "HLS playlist" if is_playlist else f"{len(head)} bytes ({response.headers.get('Content-Type', '?')})"
    return Verdict(name, host, True, kind)


def _sources() -> list[tuple[str, str]]:
    from app.kernel.container import resolve
    from app.modules.catalog.services import CatalogAdminService
    from app.modules.live.services import LiveChannelService

    channels, _ = resolve(CatalogAdminService).list_channels(page=1, per_page=200, search=None, include_inactive=False)
    found = [(c.name, c.stream_url) for c in channels]
    found += [(c.name, c.upstream_url) for c in resolve(LiveChannelService).list_admin() if c.upstream_url]
    return found


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles (cp125x)
    args = sys.argv[1:] if argv is None else argv

    from app.kernel.container import resolve
    from app.kernel.security.egress import EgressGateway
    from app.wsgi import app

    with app.app_context():
        gateway = resolve(EgressGateway)
        targets = [(u, u) for u in args] if args else _sources()
        if not targets:
            print("No stream sources found (run: python -m tools.seed_demo).")
            return 0
        verdicts = [check(gateway, name, url) for name, url in targets]
    width = max(len(v.name) for v in verdicts)
    for v in verdicts:
        print(f"{'OK  ' if v.ok else 'FAIL'}  {v.name:<{width}}  {v.host:<38}  {v.detail}")
    failed = sum(not v.ok for v in verdicts)
    print(f"\n{len(verdicts) - failed}/{len(verdicts)} reachable from this server.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
