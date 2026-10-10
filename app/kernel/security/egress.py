"""Egress gateway — the application's single door to the outside world.

Every outbound HTTP request (playlist fetch, HLS proxy, stream probing,
payment providers, captcha) goes through here. ``requests``/``httpx`` must
not be imported anywhere else (import-linter contract ``egress``).

Protections: scheme/port allow-list, optional host allow-list, DNS
resolution + "public IP only" check on *every* redirect hop (manual redirect
following), TLS verification on by default with an explicit exception list,
bounded timeouts, bounded body reads.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import requests

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; NeoTV/2.0; +https://neotv.local)"


class EgressDeniedError(Exception):
    def __init__(self, reason: str, url: str) -> None:
        super().__init__(f"egress denied ({reason}): {url}")
        self.reason = reason
        self.url = url


class EgressBodyTooLargeError(Exception):
    pass


class EgressNetworkError(Exception):
    """Transport failure (DNS/TCP/TLS/timeout/broken body) — wraps the HTTP client's exceptions so
    no other module needs to import ``requests``."""


@dataclass(frozen=True)
class EgressPolicy:
    allowed_schemes: frozenset[str] = frozenset({"http", "https"})
    allowed_ports: frozenset[int] = frozenset({80, 443, 8080, 8000, 8443})
    insecure_tls_hosts: frozenset[str] = frozenset()
    max_redirects: int = 3
    connect_timeout: float = 3.05
    read_timeout: float = 15.0


Resolver = Callable[[str, int], list[str]]


def _system_resolver(host: str, port: int) -> list[str]:
    return [str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


@dataclass
class EgressGateway:
    policy: EgressPolicy = field(default_factory=EgressPolicy)
    resolver: Resolver = _system_resolver
    session: requests.Session = field(default_factory=requests.Session)

    def check(self, url: str, *, host_allowlist: frozenset[str] | None = None) -> None:
        parts = urlsplit(url)
        if parts.scheme not in self.policy.allowed_schemes:
            raise EgressDeniedError("scheme", url)
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise EgressDeniedError("no_host", url)
        try:
            port = parts.port or (443 if parts.scheme == "https" else 80)
        except ValueError as exc:
            raise EgressDeniedError("port", url) from exc
        if port not in self.policy.allowed_ports:
            raise EgressDeniedError("port", url)
        if host_allowlist is not None and not _host_allowed(host, host_allowlist):
            raise EgressDeniedError("host_not_allowlisted", url)
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        addresses = [str(literal)] if literal else self._resolve(host, port, url)
        for address in addresses:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
            if not ip.is_global:
                raise EgressDeniedError(f"non_public_ip:{ip}", url)

    def get(
        self,
        url: str,
        *,
        stream: bool = True,
        headers: dict[str, str] | None = None,
        host_allowlist: frozenset[str] | None = None,
    ) -> requests.Response:
        current = url
        merged = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "*/*", **(headers or {})}
        for _ in range(self.policy.max_redirects + 1):
            self.check(current, host_allowlist=host_allowlist)
            host = (urlsplit(current).hostname or "").lower()
            try:
                response = self.session.get(
                    current,
                    headers=merged,
                    stream=stream,
                    allow_redirects=False,
                    timeout=(self.policy.connect_timeout, self.policy.read_timeout),
                    verify=host not in self.policy.insecure_tls_hosts,
                )
            except requests.RequestException as exc:
                raise EgressNetworkError(f"{type(exc).__name__}: {current}") from exc
            if not response.is_redirect:
                response.url = current  # final URL after manual redirects
                return response
            location = response.headers.get("Location", "")
            response.close()
            current = urljoin(current, location)
        raise EgressDeniedError("too_many_redirects", url)

    def post_json(self, url: str, payload: dict, *, headers: dict[str, str] | None = None) -> requests.Response:
        self.check(url)
        host = (urlsplit(url).hostname or "").lower()
        try:
            return self.session.post(
                url,
                json=payload,
                headers={"User-Agent": DEFAULT_USER_AGENT, **(headers or {})},
                allow_redirects=False,
                timeout=(self.policy.connect_timeout, self.policy.read_timeout),
                verify=host not in self.policy.insecure_tls_hosts,
            )
        except requests.RequestException as exc:
            raise EgressNetworkError(f"{type(exc).__name__}: {url}") from exc

    @staticmethod
    def read_capped(response: requests.Response, limit: int, chunk: int = 64 * 1024) -> bytes:
        buffer = bytearray()
        try:
            for part in response.iter_content(chunk):
                buffer += part
                if len(buffer) > limit:
                    raise EgressBodyTooLargeError(f"body exceeds {limit} bytes")
        except requests.RequestException as exc:
            raise EgressNetworkError(f"{type(exc).__name__} while reading body") from exc
        finally:
            response.close()
        return bytes(buffer)

    @staticmethod
    def iter_body(response: requests.Response, chunk: int = 64 * 1024) -> Iterator[bytes]:
        try:
            yield from response.iter_content(chunk)
        except requests.RequestException as exc:
            raise EgressNetworkError(f"{type(exc).__name__} while streaming body") from exc
        finally:
            response.close()

    def _resolve(self, host: str, port: int, url: str) -> list[str]:
        try:
            addresses = self.resolver(host, port)
        except OSError as exc:
            raise EgressDeniedError("dns", url) from exc
        if not addresses:
            raise EgressDeniedError("dns", url)
        return addresses


def _host_allowed(host: str, allowlist: frozenset[str]) -> bool:
    return any(host == allowed or host.endswith("." + allowed) for allowed in allowlist)
