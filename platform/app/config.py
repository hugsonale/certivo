from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CERTIVO_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "sqlite:///./certivo_dev.db"
    attestation_signing_key: str | None = None  # base64url, 32-byte Ed25519 seed
    attestation_key_id: str = "att-dev-1"
    max_clock_skew_ms: int = 30_000
    max_interval_ms: int = 60_000
    # Only honoured when env == "dev": the app then runs `alembic upgrade head` at startup.
    # In every other environment migrations are run explicitly, never by the app.
    auto_migrate: bool = True
