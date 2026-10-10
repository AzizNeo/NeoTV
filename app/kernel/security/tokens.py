"""JWT issuing/verification with strict claim discipline.

* Every token carries ``typ`` (access/profile/playback), ``aud``, ``iss``,
  ``jti``, ``ver`` (token version for revocation) and a **string** ``sub``.
* Verification requires all of them and checks ``typ`` — a profile token can
  never be used as an access token and vice versa (token-confusion, SEC-05).
* Each token type is signed with its own derived key (key separation).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import jwt


class TokenType(StrEnum):
    ACCESS = "access"
    PROFILE = "profile_ctx"
    PLAYBACK = "playback"


class TokenInvalidError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.error_code = code


@dataclass(frozen=True, slots=True)
class TokenClaims:
    sub: str
    typ: TokenType
    ver: int
    jti: str
    exp: int
    extra: Mapping[str, Any] = field(default_factory=dict)


_RESERVED = frozenset({"iss", "aud", "sub", "typ", "ver", "jti", "iat", "nbf", "exp"})


class TokenService:
    def __init__(
        self,
        keys: Mapping[TokenType, bytes],
        ttl: Mapping[TokenType, int],
        *,
        issuer: str = "neotv",
        audience: str = "neotv-api",
        leeway: int = 10,
    ) -> None:
        missing = [t for t in TokenType if t not in keys or t not in ttl]
        if missing:
            raise ValueError(f"missing key/ttl for token types: {missing}")
        self._keys = dict(keys)
        self._ttl = dict(ttl)
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway

    def ttl(self, typ: TokenType) -> int:
        return self._ttl[typ]

    def issue(self, *, sub: int | str, typ: TokenType, ver: int, ttl: int | None = None, **extra: Any) -> str:
        clash = _RESERVED & extra.keys()
        if clash:
            raise ValueError(f"reserved claim(s) in extra: {sorted(clash)}")
        now = int(time.time())
        payload = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(sub),
            "typ": typ.value,
            "ver": int(ver),
            "jti": uuid.uuid4().hex,
            "iat": now,
            "nbf": now,
            "exp": now + (ttl or self._ttl[typ]),
            **extra,
        }
        return jwt.encode(payload, self._keys[typ], algorithm="HS256")

    def verify(self, token: str, *, expected: TokenType) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._keys[expected],
                algorithms=["HS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "nbf", "sub", "typ", "ver", "jti", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenInvalidError("TOKEN_EXPIRED") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenInvalidError("TOKEN_INVALID") from exc
        if payload.get("typ") != expected.value:
            raise TokenInvalidError("TOKEN_TYPE_MISMATCH")
        return TokenClaims(
            sub=str(payload["sub"]),
            typ=TokenType(payload["typ"]),
            ver=int(payload["ver"]),
            jti=str(payload["jti"]),
            exp=int(payload["exp"]),
            extra={k: v for k, v in payload.items() if k not in _RESERVED},
        )
