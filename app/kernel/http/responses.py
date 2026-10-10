"""Success envelope: {"success": true, "data": ..., "message"?: ...}."""

from __future__ import annotations

from typing import Any

from flask import Response, jsonify


def ok(
    data: Any = None,
    *,
    status: int = 200,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    body: dict[str, Any] = {"success": True, "data": data}
    if message:
        body["message"] = message
    response = jsonify(body)
    response.status_code = status
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def no_content() -> Response:
    return Response(status=204)
