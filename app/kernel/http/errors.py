"""Error taxonomy and the JSON error envelope.

Domain code raises domain exceptions (HTTP-agnostic). Modules map them to
(status, code) in their manifest ``error_map``; the kernel renders them.
Unknown exceptions become 500 with an incident id (stack trace logged,
never leaked to the client).

Envelope: {"success": false, "error": {"code", "message", "request_id", "details"?}}
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from flask import Flask, Response, g, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

_log = logging.getLogger("http.errors")


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        status: int = 400,
        message: str | None = None,
        *,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.status = status
        self.message = message or code
        self.details = details
        self.headers = headers or {}


class DuplicateErrorMappingError(RuntimeError):
    pass


class ErrorMap:
    def __init__(self) -> None:
        self._map: dict[type[BaseException], tuple[int, str, str]] = {}

    def register(self, exception: type[BaseException], *, status: int, code: str, owner: str) -> None:
        existing = self._map.get(exception)
        if existing is not None:
            raise DuplicateErrorMappingError(
                f"{exception.__qualname__} is mapped by both '{existing[2]}' and '{owner}'"
            )
        self._map[exception] = (status, code, owner)

    def lookup(self, error: BaseException) -> tuple[int, str] | None:
        for klass in type(error).__mro__:
            mapped = self._map.get(klass)
            if mapped is not None:
                return mapped[0], mapped[1]
        return None

    def describe(self) -> dict[str, dict[str, Any]]:
        return {
            exc.__qualname__: {"status": s, "code": c, "owner": o}
            for exc, (s, c, o) in sorted(self._map.items(), key=lambda kv: kv[0].__qualname__)
        }


def error_response(
    code: str,
    status: int,
    message: str | None = None,
    *,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> Response:
    body: dict[str, Any] = {
        "success": False,
        "error": {"code": code, "message": message or code, "request_id": g.get("request_id")},
    }
    if details is not None:
        body["error"]["details"] = details
    response = jsonify(body)
    response.status_code = status
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def install_error_handlers(app: Flask, error_map: ErrorMap) -> None:
    @app.errorhandler(ApiError)
    def _api_error(err: ApiError) -> Response:
        return error_response(err.code, err.status, err.message, details=err.details, headers=err.headers)

    @app.errorhandler(ValidationError)
    def _validation(err: ValidationError) -> Response:
        return error_response(
            "VALIDATION_FAILED",
            422,
            "Request validation failed",
            details=err.errors(include_url=False, include_context=False, include_input=False),
        )

    @app.errorhandler(HTTPException)
    def _http(err: HTTPException) -> Response:
        status = err.code or 500
        return error_response(f"HTTP_{status}", status, err.description)

    @app.errorhandler(Exception)
    def _unhandled(err: Exception) -> Response:
        mapped = error_map.lookup(err)
        if mapped is not None:
            status, default_code = mapped
            code = getattr(err, "error_code", None) or default_code  # exceptions may refine the code
            details = getattr(err, "details", None)
            return error_response(code, status, str(err) or code, details=details)
        incident = uuid.uuid4().hex[:12]
        _log.exception("http.unhandled incident=%s", incident)
        return error_response("INTERNAL_ERROR", 500, "Unexpected server error", details={"incident": incident})
