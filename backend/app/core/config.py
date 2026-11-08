"""Application settings, loaded from environment variables (and backend/.env in development).

Secrets are never given defaults that would work in production: if JWT_SECRET_KEY or
CSV_ENCRYPTION_KEY are missing the app refuses to start (except when APP_ENV=test).
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env", override=False)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in os.environ.get(name, default).split(",") if p.strip()]


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'foliolens.db'}"))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:5173"))
    trusted_hosts: list[str] = field(default_factory=lambda: _list("TRUSTED_HOSTS", "*"))
    force_https: bool = field(default_factory=lambda: _bool("FORCE_HTTPS", False))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))

    # JWT / sessions
    jwt_secret_key: str = field(default_factory=lambda: os.environ.get("JWT_SECRET_KEY", ""))
    jwt_issuer: str = field(default_factory=lambda: os.environ.get("JWT_ISSUER", "foliolens-api"))
    jwt_audience: str = field(default_factory=lambda: os.environ.get("JWT_AUDIENCE", "foliolens-web"))
    access_token_minutes: int = field(default_factory=lambda: _int("ACCESS_TOKEN_EXPIRE_MINUTES", 15))
    refresh_token_days: int = field(default_factory=lambda: _int("REFRESH_TOKEN_EXPIRE_DAYS", 7))
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", False))
    cookie_samesite: str = field(default_factory=lambda: os.environ.get("COOKIE_SAMESITE", "lax").lower())
    cookie_domain: str | None = field(default_factory=lambda: os.environ.get("COOKIE_DOMAIN") or None)

    # Rate limits ("count/seconds")
    login_rate_limit: str = field(default_factory=lambda: os.environ.get("LOGIN_RATE_LIMIT", "5/60"))
    register_rate_limit: str = field(default_factory=lambda: os.environ.get("REGISTER_RATE_LIMIT", "5/3600"))
    refresh_rate_limit: str = field(default_factory=lambda: os.environ.get("REFRESH_RATE_LIMIT", "30/60"))
    api_rate_limit: str = field(default_factory=lambda: os.environ.get("API_RATE_LIMIT", "120/60"))

    # CSV handling
    csv_encryption_key: str = field(default_factory=lambda: os.environ.get("CSV_ENCRYPTION_KEY", ""))
    csv_max_bytes: int = field(default_factory=lambda: _int("CSV_MAX_BYTES", 1_048_576))
    csv_max_rows: int = field(default_factory=lambda: _int("CSV_MAX_ROWS", 5000))
    csv_upload_ttl_minutes: int = field(default_factory=lambda: _int("CSV_UPLOAD_TTL_MINUTES", 30))

    # Market data
    market_data_provider: str = field(default_factory=lambda: os.environ.get("MARKET_DATA_PROVIDER", "yahoo").lower())
    market_data_api_key: str = field(default_factory=lambda: os.environ.get("MARKET_DATA_API_KEY", ""))
    quote_cache_seconds: int = field(default_factory=lambda: _int("QUOTE_CACHE_SECONDS", 120))
    profile_cache_seconds: int = field(default_factory=lambda: _int("PROFILE_CACHE_SECONDS", 86400))
    history_cache_seconds: int = field(default_factory=lambda: _int("HISTORY_CACHE_SECONDS", 3600))
    stale_after_seconds: int = field(default_factory=lambda: _int("STALE_AFTER_SECONDS", 900))
    ticker_suffixes: list[str] = field(default_factory=lambda: [
        x.strip().upper() for x in os.environ.get("TICKER_SUFFIXES", ".NS,.BO,").split(",")])
    provider_timeout_seconds: int = field(default_factory=lambda: _int("PROVIDER_TIMEOUT_SECONDS", 12))

    # News
    news_provider: str = field(default_factory=lambda: os.environ.get("FINANCIAL_NEWS_PROVIDER", "yahoo").lower())
    news_api_key: str = field(default_factory=lambda: os.environ.get("FINANCIAL_NEWS_API_KEY", ""))
    news_cache_seconds: int = field(default_factory=lambda: _int("NEWS_CACHE_SECONDS", 900))

    # AI
    ai_provider: str = field(default_factory=lambda: os.environ.get("AI_PROVIDER", "anthropic").lower())
    ai_api_key: str = field(default_factory=lambda: os.environ.get("AI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", ""))
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", "claude-opus-5-5"))
    ai_timeout_seconds: int = field(default_factory=lambda: _int("AI_TIMEOUT_SECONDS", 60))

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def csv_key_bytes(self) -> bytes:
        try:
            key = base64.b64decode(self.csv_encryption_key, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ConfigError("CSV_ENCRYPTION_KEY must be base64-encoded 32 random bytes.") from exc
        if len(key) != 32:
            raise ConfigError("CSV_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256).")
        return key

    def validate(self) -> None:
        if len(self.jwt_secret_key) < 32:
            raise ConfigError("JWT_SECRET_KEY is missing or shorter than 32 characters. See backend/.env.example.")
        self.csv_key_bytes()
        if self.cookie_samesite not in {"lax", "strict", "none"}:
            raise ConfigError("COOKIE_SAMESITE must be lax, strict or none.")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ConfigError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")
        if self.is_production and not (self.cookie_secure and self.force_https):
            raise ConfigError("In production COOKIE_SECURE and FORCE_HTTPS must both be true.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
