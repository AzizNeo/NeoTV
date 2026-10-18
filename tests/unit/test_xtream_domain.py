"""xtream credential rules: generated from the TV-remote alphabet, digests keyed and per-username."""

from __future__ import annotations

from app.modules.xtream.domain import ALPHABET, digests_match, generate, is_well_formed, secret_digest


def test_alphabet_has_no_look_alikes() -> None:
    assert len(set(ALPHABET)) == len(ALPHABET) == 31
    assert not set("0o1li") & set(ALPHABET)


def test_generated_values_are_well_formed_and_differ() -> None:
    values = {generate(12) for _ in range(200)}
    assert len(values) == 200 and all(is_well_formed(v, 12) for v in values)
    assert not is_well_formed("abc", 12) and not is_well_formed("A" * 12, 12)


def test_digest_depends_on_the_key_and_the_username() -> None:
    a = secret_digest(b"k1", "user1", "secret")
    assert a == secret_digest(b"k1", "user1", "secret")
    assert a != secret_digest(b"k2", "user1", "secret")  # useless without the server key
    assert a != secret_digest(b"k1", "user2", "secret")  # equal passwords never share a digest
    assert digests_match(a, a) and not digests_match(a, secret_digest(b"k1", "user1", "secreu"))
