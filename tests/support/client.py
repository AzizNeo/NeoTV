"""Thin API test client: envelope-aware assertions and auth helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask import Flask
from flask.testing import FlaskClient

PASSWORD = "Correct-Horse9"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


@dataclass
class Reply:
    status: int
    body: Any
    headers: Any
    raw: bytes

    @property
    def data(self) -> Any:
        return self.body["data"] if isinstance(self.body, dict) else None

    @property
    def code(self) -> str | None:
        return self.body["error"]["code"] if isinstance(self.body, dict) and "error" in self.body else None


class Api:
    def __init__(self, app: Flask) -> None:
        self.app = app
        self.client: FlaskClient = app.test_client()

    def call(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
        **kw: Any,
    ) -> Reply:
        h = {"User-Agent": UA, **(headers or {})}
        if token:
            h["Authorization"] = f"Bearer {token}"
        resp = self.client.open(path, method=method, json=json, data=data, headers=h, **kw)
        return Reply(resp.status_code, resp.get_json(silent=True), resp.headers, resp.data)

    def get(self, path: str, **kw: Any) -> Reply:
        return self.call("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Reply:
        return self.call("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> Reply:
        return self.call("PUT", path, **kw)

    def patch(self, path: str, **kw: Any) -> Reply:
        return self.call("PATCH", path, **kw)

    def delete(self, path: str, **kw: Any) -> Reply:
        return self.call("DELETE", path, **kw)

    # ── auth helpers ────────────────────────────────────────────────────────
    def register(self, username: str, password: str = PASSWORD, email: str | None = None) -> Reply:
        return self.post("/api/v1/auth/register", json={"username": username, "password": password, "email": email})

    def login(self, username: str, password: str = PASSWORD, **kw: Any) -> Reply:
        return self.post("/api/v1/auth/login", json={"username": username, "password": password}, **kw)

    def user(self, username: str, *, role: str = "user") -> str:
        """Register (+ optionally promote) and return an access token."""
        assert self.register(username).status == 201
        if role != "user":
            from app.kernel.db import db
            from app.modules.identity.models import User

            with self.app.app_context():
                user = db.session.query(User).filter_by(username=username).one()
                user.role = role
                db.session.commit()
        reply = self.login(username)
        assert reply.status == 200, reply.body
        return str(reply.data["access_token"])

    def channel(
        self, admin: str, name: str, *, group: str = "News", rating: str = "general", kind: str = "vod"
    ) -> dict[str, Any]:
        reply = self.post(
            "/api/v1/catalog/admin/channels",
            token=admin,
            json={
                "name": name,
                "stream_url": f"https://cdn.example.com/{name.replace(' ', '_')}.m3u8",
                "group": group,
                "rating": rating,
                "kind": kind,
            },
        )
        assert reply.status == 201, reply.body
        return dict(reply.data)

    def open_session(self, token: str, ref: str, **kw: Any) -> Reply:
        return self.post("/api/v1/playback/sessions", token=token, json={"content_ref": ref}, **kw)
