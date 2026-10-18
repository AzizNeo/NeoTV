"""Pure rules for Xtream app credentials (no Flask, no SQLAlchemy).

An app credential is a username + password pair that a TV app (an "Xtream Codes" client) sends in
every request — in the query string or in the URL path. It is therefore never the account password:
it is generated, shown once, bound to one profile, and revocable on its own.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

#: Lower-case letters and digits without the look-alikes 0/o, 1/l/i — typed on a TV remote.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
USERNAME_LENGTH = 10
PASSWORD_LENGTH = 12  # 31^12 ≈ 2^59: online guessing only (the digest is keyed), with rate limits on top
MAX_ACTIVE_PER_USER = 10
LABEL_MAX = 40
#: last_used_at is a hint for the owner ("used 3 days ago"), not an audit log: write it at most this often.
LAST_USED_RESOLUTION_S = 300


class CredentialNotFoundError(Exception):
    pass


class CredentialLimitReachedError(Exception):
    pass


class KidsProfileManagementError(Exception):
    """App credentials are account settings: a kids profile neither sees nor changes them."""


class ProfileNotOwnedError(Exception):
    pass


class ProfileLockedError(Exception):
    """The target profile has a PIN and is not the profile the PIN was entered for in this session."""


@dataclass(frozen=True, slots=True)
class XtreamPrincipal:
    """Who a valid app credential acts as (resolved on every request, never cached)."""

    credential_id: int
    user_id: int
    profile_id: int
    is_kids: bool


def generate(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def is_well_formed(value: str, length: int) -> bool:
    return len(value) == length and all(ch in ALPHABET for ch in value)


def secret_digest(key: bytes, username: str, password: str) -> str:
    """Keyed digest (HMAC-SHA256): a leaked table is useless without the server key.

    The username is part of the message so equal passwords never share a digest. A slow KDF is not
    needed: the password is random (≈59 bits), not chosen by a person.
    """
    return hmac.new(key, f"{username}\x00{password}".encode(), hashlib.sha256).hexdigest()


def digests_match(expected: str, actual: str) -> bool:
    return hmac.compare_digest(expected.encode(), actual.encode())
