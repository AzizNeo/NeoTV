"""Idempotency-Key support for unsafe endpoints.

* The key is scoped by principal + endpoint scope and **bound to a request
  fingerprint** (method, path, body). Re-using a key with a different body is
  rejected (422 IDEMPOTENCY_KEY_REUSED) instead of replaying a wrong response.
* Concurrent duplicates do not block a worker thread: 409 + Retry-After.
* The in-flight lock is token-owned; release never deletes a foreign lock.
"""

from __future__ import annotations

import functools
import hashlib
import json
import uuid
from collections.abc import Callable
from typing import Any

from flask import Response, g, jsonify, make_response, request

_RELEASE = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end return 0"
MAX_KEY_LENGTH = 128


def _fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(request.method.encode())
    digest.update(b"\0")
    digest.update(request.path.encode())
    digest.update(b"\0")
    digest.update(request.get_data(cache=True) or b"")
    return digest.hexdigest()


def idempotent(
    scope: str, *, ttl: int = 24 * 3600, lock_ttl: int = 30
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    from app.kernel.container import resolve
    from app.kernel.http.errors import ApiError
    from app.kernel.security.auth import current_principal

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            key = request.headers.get("Idempotency-Key")
            if not key:
                return fn(*args, **kwargs)
            if len(key) > MAX_KEY_LENGTH or not key.isprintable():
                raise ApiError("IDEMPOTENCY_KEY_INVALID", 400)

            redis = resolve("kernel.redis")
            principal = current_principal()
            who = f"user:{principal.id}" if principal.is_authenticated else f"ip:{request.remote_addr}"
            base = f"idem:{scope}:{who}:{hashlib.sha256(key.encode()).hexdigest()}"
            fingerprint = _fingerprint()

            cached = redis.get(base)
            if cached:
                envelope = json.loads(cached)
                if envelope["fp"] != fingerprint:
                    raise ApiError("IDEMPOTENCY_KEY_REUSED", 422, "Idempotency-Key was used with a different request")
                replay = make_response(jsonify(envelope["body"]), envelope["status"])
                replay.headers["Idempotent-Replayed"] = "true"
                return replay

            token = uuid.uuid4().hex
            if not redis.set(f"{base}:lock", token, nx=True, ex=lock_ttl):
                raise ApiError("REQUEST_IN_PROGRESS", 409, headers={"Retry-After": "1"})
            try:
                g.idempotency_key = key
                response: Response = make_response(fn(*args, **kwargs))
                if 200 <= response.status_code < 300 and response.is_json:
                    redis.set(
                        base,
                        json.dumps({"fp": fingerprint, "status": response.status_code, "body": response.get_json()}),
                        ex=ttl,
                    )
                return response
            finally:
                redis.eval(_RELEASE, 1, f"{base}:lock", token)

        return wrapper

    return decorator
