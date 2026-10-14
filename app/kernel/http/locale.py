"""The language a request wants its *content* in.

Clients send ``Accept-Language`` (the web app always sends the interface language), so a
response is a function of the URL + that header — responses that use it must say
``Vary: Accept-Language`` (see :func:`vary_on_language`) so no cache serves one language's
answer to another.
"""

from __future__ import annotations

from flask import Response, request

from app.shared_kernel.locale import DEFAULT_LOCALE, negotiate


def request_locale() -> str:
    return negotiate(request.headers.get("Accept-Language")) or DEFAULT_LOCALE


def vary_on_language(response: Response) -> Response:
    """``Blueprint.after_request`` hook for blueprints whose answers depend on :func:`request_locale`."""
    response.vary.add("Accept-Language")
    return response
