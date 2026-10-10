"""Pure domain rules of the modules (no app, no database)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.kernel.security.tokens import TokenInvalidError, TokenService, TokenType
from app.modules.billing.domain import (
    DEFAULT_CATALOG,
    IllegalTransitionError,
    PlanId,
    SubscriptionState,
    SubStatus,
    UnknownPlanError,
    add_cycle,
    effective_plan,
    lifecycle_status,
    transition,
)
from app.modules.catalog.parsing import parse_text
from app.modules.drm.api import LicenseRequest, LicenseRestrictions
from app.modules.drm.domain import (
    DrmSystem,
    LicenseChallengeError,
    lowest_resolution,
    parse_device_classes,
    parse_systems,
)
from app.modules.drm.issuers import ClearKeyLicenseIssuer
from app.modules.drm.vault import FernetKeyVault, KeyVaultError
from app.modules.live.transcoding import LADDER, build_command, master_playlist
from app.shared_kernel.user_agent import parse_user_agent
from tests.support.factory import make_settings

NOW = datetime(2026, 1, 31, 12, tzinfo=UTC)
GRACE = timedelta(days=3)

# ── billing ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (datetime(2026, 1, 31, tzinfo=UTC), datetime(2026, 2, 28, tzinfo=UTC)),
        (datetime(2024, 1, 31, tzinfo=UTC), datetime(2024, 2, 29, tzinfo=UTC)),
        (datetime(2026, 12, 15, tzinfo=UTC), datetime(2027, 1, 15, tzinfo=UTC)),
    ],
)
def test_monthly_cycle_is_calendar_correct(start: datetime, expected: datetime) -> None:
    assert add_cycle(start, "monthly") == expected


def test_forever_cycle_has_no_period() -> None:
    with pytest.raises(ValueError):
        add_cycle(NOW, "forever")


def test_state_machine_rejects_illegal_moves() -> None:
    assert transition("trial", SubStatus.ACTIVE) is SubStatus.ACTIVE
    with pytest.raises(IllegalTransitionError) as info:
        transition("expired", SubStatus.GRACE)
    assert info.value.details == {"from": "expired", "to": "grace"}


def _state(plan: str, status: str, **kw: datetime | None) -> SubscriptionState:
    return SubscriptionState(
        plan=plan,
        status=status,
        current_period_end=kw.get("end"),
        trial_ends_at=kw.get("trial"),
        grace_ends_at=kw.get("grace"),
    )


def test_effective_plan_is_defensive_against_lagging_expiry_job() -> None:
    expired_trial = _state("family", "trial", trial=NOW - timedelta(minutes=1))
    assert effective_plan(expired_trial, DEFAULT_CATALOG, NOW, GRACE).id is PlanId.FREE
    late_renewal = _state("duo", "active", end=NOW - timedelta(days=1))  # still inside grace
    assert effective_plan(late_renewal, DEFAULT_CATALOG, NOW, GRACE).id is PlanId.DUO
    way_late = _state("duo", "active", end=NOW - timedelta(days=4))
    assert effective_plan(way_late, DEFAULT_CATALOG, NOW, GRACE).id is PlanId.FREE
    cancelled_running = _state("personal", "cancelled", end=NOW + timedelta(days=3))
    assert effective_plan(cancelled_running, DEFAULT_CATALOG, NOW, GRACE).id is PlanId.PERSONAL
    retired_plan = _state("platinum", "active", end=NOW + timedelta(days=3))
    assert effective_plan(retired_plan, DEFAULT_CATALOG, NOW, GRACE).id is PlanId.FREE


def test_free_tier_is_no_paid_lifecycle() -> None:
    assert lifecycle_status(_state("free", "active")) is SubStatus.EXPIRED


def test_catalogue_is_the_single_source_of_entitlements() -> None:
    assert DEFAULT_CATALOG.get("family").entitlements.max_streams == 5
    assert all(p.price_minor >= 0 and isinstance(p.price_minor, int) for p in DEFAULT_CATALOG.all())
    with pytest.raises(UnknownPlanError):
        DEFAULT_CATALOG.get("enterprise")


# ── drm ────────────────────────────────────────────────────────────────────


def test_drm_value_parsing() -> None:
    assert parse_systems("clearkey, aes-128") == {DrmSystem.CLEARKEY, DrmSystem.AES_128}
    with pytest.raises(ValueError):
        parse_systems("")
    with pytest.raises(ValueError):
        parse_device_classes("desktop,toaster")
    assert lowest_resolution("2160p", "480p", None, "bogus") == "480p"
    assert lowest_resolution() == "2160p"


def _clearkey_request(challenge: bytes, *, offline: bool = False) -> LicenseRequest:
    restrictions = LicenseRestrictions("1080p", False, False, offline, 48)
    return LicenseRequest(
        "clearkey", challenge, "00112233445566778899aabbccddeeff", b"\x01" * 16, restrictions, NOW, 1, "tok"
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_clearkey_issues_only_the_sessions_key() -> None:
    kid = _b64(bytes.fromhex("00112233445566778899aabbccddeeff"))
    issued = ClearKeyLicenseIssuer().issue(_clearkey_request(json.dumps({"kids": [kid]}).encode()))
    body = json.loads(issued.body)
    assert body["keys"] == [{"kty": "oct", "kid": kid, "k": _b64(b"\x01" * 16)}]
    assert body["type"] == "temporary"
    for challenge in (b"not json", b'{"kids": "x"}', json.dumps({"kids": [_b64(b"\x02" * 16)]}).encode()):
        with pytest.raises(LicenseChallengeError):
            ClearKeyLicenseIssuer().issue(_clearkey_request(challenge))


def test_clearkey_persistent_license_requires_offline_entitlement() -> None:
    kid = _b64(bytes.fromhex("00112233445566778899aabbccddeeff"))
    challenge = json.dumps({"kids": [kid], "type": "persistent-license"}).encode()
    assert json.loads(ClearKeyLicenseIssuer().issue(_clearkey_request(challenge)).body)["type"] == "temporary"
    issued = ClearKeyLicenseIssuer().issue(_clearkey_request(challenge, offline=True))
    assert json.loads(issued.body)["type"] == "persistent-license"


def test_key_vault_rotation() -> None:
    from cryptography.fernet import Fernet

    old, new = Fernet.generate_key(), Fernet.generate_key()
    wrapped = FernetKeyVault([old]).wrap(b"content-key")
    rotated_vault = FernetKeyVault([new, old])
    assert rotated_vault.unwrap(wrapped) == b"content-key"
    rewrapped = rotated_vault.rewrap(wrapped)
    assert FernetKeyVault([new]).unwrap(rewrapped) == b"content-key"
    with pytest.raises(KeyVaultError):
        FernetKeyVault([new]).unwrap(wrapped)


# ── tokens ─────────────────────────────────────────────────────────────────


def _tokens() -> TokenService:
    keys = {t: f"key-{t}".encode() * 4 for t in TokenType}
    return TokenService(keys, dict.fromkeys(TokenType, 60))


def test_token_types_are_not_interchangeable() -> None:
    tokens = _tokens()
    access = tokens.issue(sub=1, typ=TokenType.ACCESS, ver=1)
    assert tokens.verify(access, expected=TokenType.ACCESS).sub == "1"
    with pytest.raises(TokenInvalidError):
        tokens.verify(access, expected=TokenType.PROFILE)
    with pytest.raises(TokenInvalidError):
        tokens.verify(access + "x", expected=TokenType.ACCESS)


# ── settings ───────────────────────────────────────────────────────────────


def test_prod_invariants_fail_loudly() -> None:
    with pytest.raises(ValidationError) as info:
        make_settings(env="prod")
    message = str(info.value)
    for fragment in ("SQLite is not allowed", "DRM_KEK_KEYS", "PAYMENT_PROVIDER=fake", "CELERY_ALWAYS_EAGER"):
        assert fragment in message


def test_placeholder_secret_rejected_and_csv_parsed() -> None:
    with pytest.raises(ValidationError):
        make_settings(secret_key="change-me")
    settings = make_settings(disabled_modules="recommendations, drm", database_url="postgresql://u:p@h/db")
    assert settings.disabled == frozenset({"recommendations", "drm"})
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.derive_key("a") != settings.derive_key("b")


# ── catalog / live / ua ────────────────────────────────────────────────────


def test_m3u_parsing_dedupes_and_hints() -> None:
    text = (
        "#EXTM3U\n"
        '#EXTINF:-1 tvg-id="news.tr" tvg-logo="https://l/n.png" group-title="Haber",News\n'
        "https://cdn/news.m3u8\n"
        '#EXTINF:-1 group-title="Filmler",Film\n'
        "https://cdn/film.mp4\n"
        '#EXTINF:-1 tvg-id="news.tr",News again\n'
        "https://cdn/news2.m3u8\n"
        "#EXTINF:-1,Bad\n"
        "ftp://nope\n"
    )
    entries = parse_text(text)
    assert [e.name for e in entries] == ["News", "Film"]
    assert entries[0].source_key == "tvg:news.tr" and entries[1].kind_hint == "vod"


def test_transcoder_command_and_master_playlist() -> None:
    from pathlib import Path

    argv = build_command(
        source_url="rtmp://x/live/abc",
        stream_id="abc",
        output_dir=Path("/tmp/out"),
        encoder="libx264",
        ffmpeg="/opt/ffmpeg/bin/ffmpeg",  # pure unit test: no ffmpeg install required
    )
    assert argv[0] == "/opt/ffmpeg/bin/ffmpeg"
    assert "-shell" not in argv and all(isinstance(a, str) for a in argv)
    playlist = master_playlist()
    assert playlist.startswith("#EXTM3U") and playlist.count("#EXT-X-STREAM-INF") == len(LADDER)


def test_missing_ffmpeg_is_a_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    from app.modules.live.transcoding import FfmpegNotFoundError, ffmpeg_binary

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(FfmpegNotFoundError):
        ffmpeg_binary()


@pytest.mark.parametrize(
    ("ua", "device"),
    [
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile Safari", "mobile"),
        ("Mozilla/5.0 (Linux; Android 13; SM-X700) Safari", "tablet"),
        ("Mozilla/5.0 (Web0S; Linux/SmartTV)", "tv"),
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/120", "desktop"),
        ("", "unknown"),
    ],
)
def test_user_agent_classes(ua: str, device: str) -> None:
    assert parse_user_agent(ua).device_type == device
