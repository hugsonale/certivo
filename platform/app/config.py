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
    # Dev convenience. Replace with Alembic migrations before any real deployment.
    auto_create_tables: bool = True
