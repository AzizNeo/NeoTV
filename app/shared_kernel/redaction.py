"""Credentials that travel in URLs, removed before a URL is written anywhere (logs, traces).

Some clients cannot send credentials in a header: Xtream apps (ADR-0011) put a username and a
password in the query string or in the path (``/live/<user>/<password>/<id>.m3u8``), and signed
media URLs carry their grant in the query (``sig``). Every place that records a URL — the access
log, the request span — passes it through :func:`redact_target` first.

Pure functions; the shapes here are the protocols', not any module's.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode

MASK = "***"
#: Query parameters whose value is a secret or identifies a credential.
SENSITIVE_QUERY = frozenset({"username", "password", "sig", "token", "access_token"})
#: Paths with credentials as segments: /<live|movie|series|timeshift>/<user>/<password>/…, at the
#: server root (what apps call) or under the API prefix (where nginx sends it).
_CREDENTIAL_PATH = re.compile(r"^(?P<head>(?:/api/v1/xtream)?/(?:live|movie|series|timeshift)/)[^/?]*/[^/?]*(?=/)")


def redact_path(path: str) -> str:
    return _CREDENTIAL_PATH.sub(rf"\g<head>{MASK}/{MASK}", path, count=1)


def redact_query(query: str) -> str:
    if not query:
        return query
    pairs = parse_qsl(query, keep_blank_values=True)
    if not any(name.lower() in SENSITIVE_QUERY for name, _ in pairs):
        return query  # untouched: keeps the original encoding of ordinary URLs
    return urlencode([(name, MASK if name.lower() in SENSITIVE_QUERY else value) for name, value in pairs], safe="*")


def redact_target(target: str) -> str:
    """A request target (path + optional query) or a full URL, without its credentials."""
    head, sep, query = target.partition("?")
    scheme, has_authority, rest = head.partition("://")
    if has_authority:
        host, slash, path = rest.partition("/")
        head = f"{scheme}://{host}" + (redact_path(slash + path) if slash else "")
    else:
        head = redact_path(head)
    return head + (sep + redact_query(query) if sep else "")
