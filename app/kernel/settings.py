"""Typed, validated, fail-fast configuration (single source of truth).

Values are read from the process environment and from ``.env`` by
pydantic-settings itself, so there is no ``load_dotenv()`` ordering problem:
the first call to :func:`get_settings` sees the file regardless of import order.
Invalid or missing values raise ``pydantic.ValidationError`` and stop the boot.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

Environment = Literal["dev", "test", "staging", "prod"]

# Single source of truth: tools/devctl.py (init-env) imports this to decide what to regenerate.
PLACEHOLDER_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "dev",
        "dev-secret-key",
        "dev-secret-key-change-in-production",
        "changeme",
        "change-me",
        "secret",
        "your-secret-key",
        "please-change",
    }
)
_PLACEHOLDER_SECRETS = PLACEHOLDER_SECRETS


def _split_csv(value: Any) -> Any:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _default_hls_root() -> Path:
    # tmpfs keeps live HLS segments off disk; the directory is created 0700 by the transcoder.
    if sys.platform.startswith("linux") and Path("/dev/shm").is_dir():  # noqa: S108
        return Path("/dev/shm/neotv-hls")  # noqa: S108
    return Path(tempfile.gettempdir()) / "neotv-hls"


CsvList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8-sig",  # tolerate a BOM written by Windows editors
        extra="ignore",
        case_sensitive=False,
    )

    # ── Runtime ────────────────────────────────────────────────────────────
    env: Environment = "dev"
    secret_key: SecretStr = Field(min_length=32)
    log_level: str = "INFO"
    log_json: bool | None = None  # None → JSON everywhere except dev

    # ── Storage ────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///instance/database.db"
    redis_url: str = "redis://localhost:6379/1"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str | None = None
    celery_always_eager: bool = False

    # ── HTTP ───────────────────────────────────────────────────────────────
    allowed_origins: CsvList = ["http://localhost:5173", "http://127.0.0.1:5173"]
    frontend_base_url: str = "http://localhost:5173"
    trusted_proxy_count: int = Field(default=0, ge=0, le=5)

    # ── Identity / tokens ──────────────────────────────────────────────────
    access_token_ttl_s: int = Field(default=15 * 60, ge=60)
    refresh_token_ttl_s: int = Field(default=30 * 24 * 3600, ge=3600)
    profile_token_ttl_s: int = Field(default=12 * 3600, ge=300)
    playback_grant_ttl_s: int = Field(default=6 * 3600, ge=60)
    cookie_secure: bool | None = None  # None → secure everywhere except dev/test
    # Strict-Transport-Security on HTTPS responses (1 year). 0 disables it. No `preload`: joining the
    # browsers' preload list is a separate, hard-to-undo decision for the operator.
    hsts_max_age_s: int = Field(default=365 * 24 * 3600, ge=0)
    profile_context_mode: Literal["strict", "default_profile"] = "default_profile"

    # ── Modules ────────────────────────────────────────────────────────────
    disabled_modules: CsvList = []

    # ── Streaming ──────────────────────────────────────────────────────────
    hls_output_root: Path = Field(default_factory=_default_hls_root)
    hls_serve_via_nginx: bool = False
    transcode_encoders: CsvList = ["h264_nvenc", "h264_qsv", "h264_videotoolbox", "libx264"]
    transcode_idle_grace_s: int = Field(default=60, ge=10)
    ingest_callback_allowed_ips: CsvList = ["127.0.0.1", "::1"]
    rtmp_internal_base: str = "rtmp://127.0.0.1:1935/live"
    epg_xmltv_url: str | None = None
    default_max_streams: int = Field(default=1, ge=1)

    # ── Egress ─────────────────────────────────────────────────────────────
    egress_insecure_tls_hosts: CsvList = []
    egress_allowed_ports: CsvList = ["80", "443", "8080", "8000", "8443"]

    # ── DRM ────────────────────────────────────────────────────────────────
    drm_kek_keys: Annotated[list[SecretStr], NoDecode] = []

    # ── Billing ────────────────────────────────────────────────────────────
    payment_provider: Literal["fake", "hmac"] = "fake"
    payment_webhook_secret: SecretStr | None = None
    payment_checkout_url_template: str = "https://checkout.example.invalid/{session_id}"
    trial_days: int = Field(default=7, ge=1, le=60)
    grace_days: int = Field(default=3, ge=0, le=30)

    # ── E-mail (notifications module) ──────────────────────────────────────
    email_backend: str = "console"  # a transport name from notifications.email_senders
    email_from: str = "NeoTV <no-reply@localhost>"
    mail_dir: Path = Field(default_factory=lambda: PROJECT_ROOT / "var" / "mail")  # console backend output
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout_s: int = Field(default=15, ge=1, le=120)

    # ── Metadata (tmdb module) ─────────────────────────────────────────────
    # TMDB "API Read Access Token" (v4, a JWT): themoviedb.org → Settings → API. Optional — without it
    # the importer answers METADATA_PROVIDER_NOT_CONFIGURED and nothing else changes.
    tmdb_read_token: SecretStr | None = None

    # ── Observability ──────────────────────────────────────────────────────
    otel_endpoint: str | None = None  # OTLP/HTTP collector base, e.g. http://otel-collector:4318
    otel_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)  # share of new traces kept
    metrics_token: SecretStr | None = None

    # ── Validators ─────────────────────────────────────────────────────────
    @field_validator(
        "allowed_origins",
        "disabled_modules",
        "transcode_encoders",
        "ingest_callback_allowed_ips",
        "egress_insecure_tls_hosts",
        "egress_allowed_ports",
        mode="before",
    )
    @classmethod
    def _csv(cls, value: Any) -> Any:
        return _split_csv(value)

    @field_validator("drm_kek_keys", mode="before")
    @classmethod
    def _csv_secrets(cls, value: Any) -> Any:
        return _split_csv(value)

    @field_validator("secret_key")
    @classmethod
    def _reject_placeholder(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value().strip().lower() in _PLACEHOLDER_SECRETS:
            raise ValueError("SECRET_KEY is still a placeholder value; run `python -m tools.devctl init-env`")
        return value

    @field_validator("database_url")
    @classmethod
    def _absolute_sqlite(cls, value: str) -> str:
        prefix = "sqlite:///"
        if value.startswith(prefix) and value != "sqlite:///:memory:":
            raw = value[len(prefix) :]
            path = Path(raw)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            path.parent.mkdir(parents=True, exist_ok=True)
            return prefix + path.as_posix()
        if value.startswith("postgresql://"):
            # Normalise to the psycopg 3 driver.
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @model_validator(mode="after")
    def _environment_invariants(self) -> Settings:
        if self.env == "prod":
            problems: list[str] = []
            if self.database_url.startswith("sqlite"):
                problems.append("SQLite is not allowed in prod")
            if not self.drm_kek_keys:
                problems.append("DRM_KEK_KEYS is required in prod")
            if self.profile_context_mode != "strict":
                problems.append("PROFILE_CONTEXT_MODE must be 'strict' in prod")
            if self.payment_provider == "fake":
                problems.append("PAYMENT_PROVIDER=fake is not allowed in prod")
            if self.celery_always_eager:
                problems.append("CELERY_ALWAYS_EAGER must be false in prod")
            if self.email_backend in {"console", "memory"}:
                problems.append(f"EMAIL_BACKEND={self.email_backend} is not allowed in prod (use smtp)")
            if self.redis_url.startswith("fakeredis://") or self.celery_broker_url.startswith(
                ("memory://", "fakeredis://")
            ):
                problems.append("in-process Redis/broker (fakeredis://, memory://) is not allowed in prod")
            if problems:
                raise ValueError("; ".join(problems))
        if self.email_backend == "smtp" and not self.smtp_host:
            raise ValueError("SMTP_HOST is required when EMAIL_BACKEND=smtp")
        if self.payment_provider == "hmac":
            if self.payment_webhook_secret is None:
                raise ValueError("PAYMENT_WEBHOOK_SECRET is required when PAYMENT_PROVIDER=hmac")
            if "{session_id}" not in self.payment_checkout_url_template:
                raise ValueError("PAYMENT_CHECKOUT_URL_TEMPLATE must contain {session_id}")
        return self

    # ── Derived values ─────────────────────────────────────────────────────
    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.env not in {"dev", "test"}

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.env != "dev"

    @property
    def disabled(self) -> frozenset[str]:
        return frozenset(self.disabled_modules)

    @property
    def egress_ports(self) -> frozenset[int]:
        return frozenset(int(p) for p in self.egress_allowed_ports)

    def derive_key(self, purpose: str) -> bytes:
        """Purpose-bound sub-key (key separation): a leak of one derived key does
        not compromise the others and none of them equals SECRET_KEY."""
        if not purpose:
            raise ValueError("purpose is required")
        return hmac.new(
            self.secret_key.get_secret_value().encode(),
            f"neotv/derive/{purpose}".encode(),
            hashlib.sha256,
        ).digest()

    def flask_config(self) -> dict[str, Any]:
        engine_options: dict[str, Any] = {"pool_pre_ping": True}
        if self.database_url.startswith("sqlite"):
            engine_options["connect_args"] = {"check_same_thread": False, "timeout": 15}
        return {
            "ENV_NAME": self.env,
            "TESTING": self.env == "test",
            "SECRET_KEY": self.secret_key.get_secret_value(),
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "SQLALCHEMY_ENGINE_OPTIONS": engine_options,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SESSION_COOKIE_SECURE": self.secure_cookies,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "PROFILE_CONTEXT_MODE": self.profile_context_mode,
            "HLS_OUTPUT_ROOT": str(self.hls_output_root),
            "HLS_SERVE_VIA_NGINX": self.hls_serve_via_nginx,
            "MAX_CONTENT_LENGTH": 8 * 1024 * 1024,
            "JSON_SORT_KEYS": False,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment


def reset_settings_cache() -> None:
    """Testing hook — forces the next get_settings() to re-read the environment."""
    get_settings.cache_clear()


__all__ = ["PROJECT_ROOT", "Settings", "get_settings", "reset_settings_cache"]
