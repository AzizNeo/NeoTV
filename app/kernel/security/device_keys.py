"""Device key derivation (pure, shared).

A *device key* identifies "this client installation of this user" without
storing the raw client identifier. It is a keyed hash, so:
* identity (refresh tokens), devices (device list) and playback (stream
  slots) compute the same key independently — no module dependency cycle;
* two users on the same browser model never collide (RT-06): the user id is
  part of the hashed material;
* the raw ``X-Device-ID`` never reaches the database.
"""

from __future__ import annotations

import hashlib
import hmac
import re

_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
HEADER = "X-Device-ID"


class DeviceKeys:
    def __init__(self, pepper: bytes) -> None:
        if len(pepper) < 16:
            raise ValueError("device key pepper too short")
        self._pepper = pepper

    @staticmethod
    def normalise_client_id(raw: str | None) -> str | None:
        if raw and _CLIENT_ID.fullmatch(raw):
            return raw.lower()
        return None

    def key(self, user_id: int, client_device_id: str | None, user_agent: str | None) -> str:
        client = self.normalise_client_id(client_device_id)
        basis = f"id:{client}" if client else f"ua:{(user_agent or '')[:512]}"
        return hmac.new(self._pepper, f"{user_id}|{basis}".encode(), hashlib.sha256).hexdigest()[:40]
