"""OpenAPI 3.1 document generated from ``endpoint()`` metadata.

The document is the single source of the HTTP contract: the frontend
generates its types from it and CI diffs it for breaking changes.
"""

from __future__ import annotations

import re
from typing import Any

from flask import Flask
from pydantic import TypeAdapter

from app.kernel.http.endpoint import EndpointDoc

_PATH_PARAM = re.compile(r"<(?:(?P<conv>[a-z]+)(?:\((?P<args>[^)]*)\))?:)?(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>")
_CONVERTER_TYPES = {"int": "integer", "float": "number", "path": "string", "string": "string", None: "string"}

ERROR_ENVELOPE = {
    "type": "object",
    "required": ["success", "error"],
    "properties": {
        "success": {"const": False},
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "request_id": {"type": ["string", "null"]},
                "details": {},
            },
        },
    },
}


def _path_schema(match: re.Match[str]) -> dict[str, Any]:
    if match.group("conv") == "any":  # <any(a, b):name> → one of the listed values
        return {"type": "string", "enum": [v.strip().strip("'\"") for v in (match.group("args") or "").split(",")]}
    return {"type": _CONVERTER_TYPES.get(match.group("conv"), "string")}


def _schema(tp: Any, components: dict[str, Any]) -> dict[str, Any]:
    schema = TypeAdapter(tp).json_schema(ref_template="#/components/schemas/{model}", mode="serialization")
    for name, definition in schema.pop("$defs", {}).items():
        components.setdefault(name, definition)
    title = schema.get("title")
    if schema.get("type") == "object" and title and title not in components:
        components[title] = schema
        return {"$ref": f"#/components/schemas/{title}"}
    return schema


def _input_schema(tp: Any, components: dict[str, Any]) -> dict[str, Any]:
    schema = TypeAdapter(tp).json_schema(ref_template="#/components/schemas/{model}", mode="validation")
    for name, definition in schema.pop("$defs", {}).items():
        components.setdefault(name, definition)
    return schema


def build_openapi(app: Flask, *, title: str = "NeoTV API", version: str = "2.0.0") -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    components: dict[str, Any] = {"ErrorEnvelope": ERROR_ENVELOPE}

    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        view = app.view_functions.get(rule.endpoint)
        doc: EndpointDoc | None = getattr(view, "__endpoint_doc__", None)
        if doc is None:
            continue
        path = _PATH_PARAM.sub(lambda m: "{" + m.group("name") + "}", rule.rule)
        parameters: list[dict[str, Any]] = [
            {
                "name": m.group("name"),
                "in": "path",
                "required": True,
                "schema": _path_schema(m),
            }
            for m in _PATH_PARAM.finditer(rule.rule)
        ]
        if doc.query is not None:
            query_schema = _input_schema(doc.query, components)
            required = set(query_schema.get("required", []))
            for name, prop in query_schema.get("properties", {}).items():
                parameters.append({"name": name, "in": "query", "required": name in required, "schema": prop})
        if doc.profile:
            parameters.append(
                {"name": "X-Profile-Token", "in": "header", "required": False, "schema": {"type": "string"}}
            )
        if doc.idempotency:
            parameters.append(
                {"name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string"}}
            )

        data_schema = _schema(doc.response, components) if doc.response is not None else {}
        operation: dict[str, Any] = {
            "operationId": rule.endpoint.replace(".", "_"),
            "summary": doc.summary,
            "tags": list(doc.tags) or [rule.endpoint.split(".")[0]],
            "parameters": parameters,
            "responses": {
                str(doc.status): {
                    "description": "Success",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["success", "data"],
                                "properties": {
                                    "success": {"const": True},
                                    "data": data_schema,
                                    "message": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "default": {
                    "description": "Error",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}},
                },
            },
            "x-auth": doc.auth,
        }
        if doc.permission:
            operation["x-permission"] = doc.permission
        if doc.errors:
            operation["x-error-codes"] = list(doc.errors)
        if doc.deprecated:
            operation["deprecated"] = True
        if doc.auth == "user":
            operation["security"] = [{"bearer": []}]
        if doc.body is not None:
            operation["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": _input_schema(doc.body, components)}},
            }
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            paths.setdefault(path, {})[method.lower()] = operation

    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "paths": paths,
        "components": {
            "schemas": dict(sorted(components.items())),
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
        },
    }
