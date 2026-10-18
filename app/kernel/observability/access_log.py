"""gunicorn access log without credentials (``logger_class`` in gunicorn.conf.py).

gunicorn writes the raw request line, path, query string and referrer. Clients that carry a
credential in the URL (Xtream apps, signed media grants — see shared_kernel.redaction) would leave
it in every log line, so the URL-bearing atoms are redacted before formatting.
"""

from __future__ import annotations

from typing import Any

from gunicorn.glogging import Logger

from app.shared_kernel.redaction import redact_path, redact_query, redact_target


class RedactingLogger(Logger):
    def atoms(self, resp: Any, req: Any, environ: dict[str, Any], request_time: Any) -> dict[str, Any]:
        atoms: dict[str, Any] = super().atoms(resp, req, environ, request_time)
        method, protocol = environ.get("REQUEST_METHOD", "-"), environ.get("SERVER_PROTOCOL", "-")
        atoms["r"] = f"{method} {redact_target(environ.get('RAW_URI') or '')} {protocol}"
        atoms["U"] = redact_path(environ.get("PATH_INFO") or "")
        atoms["q"] = redact_query(environ.get("QUERY_STRING") or "")
        if environ.get("HTTP_REFERER"):
            atoms["f"] = redact_target(environ["HTTP_REFERER"])
        # gunicorn also offers every environ entry ({name}e) and request header ({name}i) as atoms.
        for key in _URL_ATOMS:
            if isinstance(atoms.get(key), str):
                atoms[key] = redact_query(atoms[key]) if key == "{query_string}e" else redact_target(atoms[key])
        return atoms


_URL_ATOMS = ("{raw_uri}e", "{path_info}e", "{query_string}e", "{request_uri}e", "{http_referer}e", "{referer}i")
