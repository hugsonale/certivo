from __future__ import annotations

import re
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HTTPS_ORIGIN = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?$")
_LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CERTIVO_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = "sqlite:///./certivo_dev.db"
    attestation_signing_key: str | None = None  # base64url, 32-byte Ed25519 seed. DEV AND TESTS ONLY
    attestation_key_id: str = "att-dev-1"  # the name partners see; never reuse one for a different key
    # Where the private key lives. "local" holds it in this process (dev/tests); "aws_kms" keeps it
    # in AWS KMS, where it never leaves. Production must use a managed key service (ADR 0016).
    attestation_signer: Literal["local", "aws_kms"] = "local"
    attestation_kms_key_id: str | None = None  # the KMS key ARN or alias, when signer is aws_kms
    attestation_kms_region: str | None = None
    # A signing request that failed is retried with growing waits, never longer than this (SDD 7.2).
    attestation_retry_max_wait_s: int = 60
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

    # --- Outage tolerance (P0-08). PLACEHOLDER (docs/adr/0014): to be set from measured outages.
    # A packet that reaches us later than this after its interval ended, or a hole this long between
    # two of a participant's packets, is disclosed as a coverage gap in the attestation.
    gap_disclosure_threshold_ms: int = 10_000

    # --- Retention and partitions (P0-09, docs/adr/0015).
    # NO DEFAULT for how long score events are kept: that is a privacy and legal decision (P0-52) and
    # no number has been chosen. While it is unset the maintenance job deletes nothing.
    score_event_retention_days: int | None = None
    # How long attestations are kept. Nothing deletes attestations yet. Set it only so that the rule
    # "score events are kept for less time than the attestation" is checked the moment both exist.
    attestation_retention_days: int | None = None
    partition_days_ahead: int = 7  # daily partitions made in advance (Postgres)

    # Implausible-pattern detection (P0-12, ADR 0018): flags only, never blocks. A switch for emergencies.
    anomaly_detection_enabled: bool = True

    # --- Observability (P0-13, docs/adr/0019).
    log_format: Literal["json", "text"] = "json"      # "text" is only for reading logs on your own PC
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    metrics_enabled: bool = True
    # GET /metrics needs "Authorization: Bearer <this>". Without a token it is served only when
    # CERTIVO_ENV=dev, and never in any other environment.
    metrics_token: str | None = None
    # Tracing is OFF unless switched on. It needs the packages in requirements-otel.txt.
    tracing_enabled: bool = False
    tracing_otlp_endpoint: str | None = None          # e.g. http://collector:4318/v1/traces
    tracing_service_name: str = "certivo-platform"

    # --- Webhook delivery (P0-07). Numbers are PLACEHOLDERS (docs/spec/base/05).
    redis_url: str = "redis://localhost:6379/0"      # the Celery broker
    # Key that encrypts webhook signing secrets in the database (a Fernet key; see
    # scripts/gen_webhook_key.py). Required outside dev; dev falls back to a fixed, INSECURE key.
    webhook_secret_key: str | None = None
    # Dev only: let webhooks go to localhost / private addresses (for testing against your own PC).
    webhook_allow_private_targets: bool = False
    webhook_retry_delays_s: str = "30,300,1800,7200,21600,43200"  # waits between attempts, seconds
    webhook_timeout_s: float = 10.0                  # how long we wait for a partner's reply
    webhook_poll_interval_s: float = 5.0             # how often the worker looks for work
    webhook_batch_size: int = 100                    # deliveries picked up per look
    webhook_lease_s: int = 60                        # a delivery being sent is locked this long
    webhook_replay_tolerance_s: int = 300            # advice to receivers: reject older timestamps
    webhook_secret_overlap_s: int = 86_400           # an old secret keeps signing this long after rotation
    webhook_max_endpoints_per_partner: int = 10

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

    @property
    def retry_delays_s(self) -> list[int]:
        return [int(x) for x in self.webhook_retry_delays_s.split(",") if x.strip()]

    @model_validator(mode="after")
    def _check_values(self) -> Settings:
        if self.webhook_allow_private_targets and self.env != "dev":
            raise ValueError("CERTIVO_WEBHOOK_ALLOW_PRIVATE_TARGETS may only be true when "
                             "CERTIVO_ENV=dev: outside dev, webhooks must never reach private addresses.")
        try:
            delays = self.retry_delays_s
        except ValueError:
            delays = []
        if not 1 <= len(delays) <= 12 or any(d < 1 for d in delays):
            raise ValueError("CERTIVO_WEBHOOK_RETRY_DELAYS_S must be 1 to 12 whole numbers of seconds, "
                             "comma separated, each at least 1 (for example 30,300,1800).")
        if self.webhook_timeout_s <= 0 or self.webhook_lease_s <= self.webhook_timeout_s:
            raise ValueError("webhook_timeout_s must be above 0 and webhook_lease_s must be longer "
                             "than it, or a delivery could be sent twice at once.")
        for name in ("webhook_poll_interval_s", "webhook_batch_size", "webhook_replay_tolerance_s",
                     "webhook_secret_overlap_s", "webhook_max_endpoints_per_partner"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be above 0")
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
                    "db_statement_timeout_ms", "max_api_keys_per_partner",
                    "gap_disclosure_threshold_ms", "partition_days_ahead",
                    "attestation_retry_max_wait_s")
        for name in positive:
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        if self.attestation_signer == "aws_kms" and not self.attestation_kms_key_id:
            raise ValueError("CERTIVO_ATTESTATION_KMS_KEY_ID is required when the signer is aws_kms")
        if self.env == "prod":
            if self.attestation_signing_key:
                raise ValueError(
                    "CERTIVO_ATTESTATION_SIGNING_KEY must not be set in production: signing keys "
                    "come from a managed key service, never from environment files (ADR 0016)")
            if self.attestation_signer == "local":
                raise ValueError("Production needs CERTIVO_ATTESTATION_SIGNER=aws_kms: the signing "
                                 "key must live in a managed key service (ADR 0016)")
        for name in ("score_event_retention_days", "attestation_retention_days"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(f"{name} must be at least 1 when it is set")
        if (self.score_event_retention_days is not None
                and self.attestation_retention_days is not None
                and self.score_event_retention_days >= self.attestation_retention_days):
            raise ValueError(
                "score_event_retention_days must be shorter than attestation_retention_days: the "
                "attestation is the lasting record and the per-interval scores must not outlive it "
                "(Privacy Architecture 2.2, Database Design 4.2)")
        if self.metrics_token is not None and len(self.metrics_token) < 16:
            raise ValueError("CERTIVO_METRICS_TOKEN must be at least 16 characters (or left unset)")
        if self.trusted_proxy_hops < 0 or self.body_read_timeout_s <= 0:
            raise ValueError("trusted_proxy_hops must be >= 0 and body_read_timeout_s > 0")
        return self
