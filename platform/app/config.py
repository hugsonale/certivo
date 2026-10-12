from __future__ import annotations

import re

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HTTPS_ORIGIN = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?$")
_LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")


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

    # --- Abuse hardening (P0-06). Every number below is a PLACEHOLDER to be set from measured
    # traffic (docs/spec/base/01 and 02); none is a validated value.
    sdk_token_ttl_seconds: int = 21_600          # an SDK token stops working after this long
    rate_limit_key_per_minute: int = 600         # requests per partner API key
    rate_limit_session_per_minute: int = 1_800   # requests per SDK session
    rate_limit_auth_failures_per_minute: int = 20  # failed logins per network address / key prefix
    trusted_proxy_hops: int = 0                  # how many reverse proxies we sit behind (0 = none)
    max_body_bytes: int = 65_536                 # larger request bodies are refused with 413
    body_read_timeout_s: float = 10.0            # a body that stalls this long is refused with 408
    db_statement_timeout_ms: int = 5_000         # no single database statement may run longer
    max_api_keys_per_partner: int = 50           # active keys per partner

    # Browser origins allowed to call the SDK endpoints, comma separated. Empty = none.
    cors_allowed_origins: str = ""
    # None = on in dev, off elsewhere
    enable_docs: bool | None = None

    @property
    def docs_enabled(self) -> bool:
        return self.env == "dev" if self.enable_docs is None else self.enable_docs

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _check_values(self) -> Settings:
        for origin in self.cors_origins:
            if self.env == "dev" and origin == "*":
                continue
            if _HTTPS_ORIGIN.match(origin):
                continue
            if self.env == "dev" and _LOCAL_ORIGIN.match(origin):
                continue
            raise ValueError(
                f"CERTIVO_CORS_ALLOWED_ORIGINS has an invalid origin {origin!r}: use exact "
                "https://host[:port] origins (no wildcards, no paths). Plain http://localhost "
                "and '*' are allowed only when CERTIVO_ENV=dev.")
        positive = ("sdk_token_ttl_seconds", "rate_limit_key_per_minute", "max_body_bytes",
                    "rate_limit_session_per_minute", "rate_limit_auth_failures_per_minute",
                    "db_statement_timeout_ms", "max_api_keys_per_partner")
        for name in positive:
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.trusted_proxy_hops < 0 or self.body_read_timeout_s <= 0:
            raise ValueError("trusted_proxy_hops must be >= 0 and body_read_timeout_s > 0")
        return self
