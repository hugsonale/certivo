from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Every constraint and index gets a predictable name, so later migrations can alter or drop it.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# JSON column: binary JSONB on Postgres, plain JSON elsewhere (SQLite in tests and dev).
JSONType = JSON().with_variant(JSONB(), "postgresql")
# Auto-incrementing 64-bit id: BIGINT on Postgres; SQLite only auto-increments plain INTEGER keys.
BigIntId = BigInteger().with_variant(Integer(), "sqlite")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Partner(Base):
    __tablename__ = "partners"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at_ms: Mapped[int] = mapped_column(BigInteger)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex
    key_prefix: Mapped[str] = mapped_column(String(16))
    scopes: Mapped[list] = mapped_column(JSONType)  # list of scope names (app/scopes.py)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    last_used_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revoked_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Policy(Base):
    """partner_id NULL = global default available to every partner."""

    __tablename__ = "policies"
    __table_args__ = (
        UniqueConstraint("partner_id", "use_case", "version",
                         name="uq_policies_partner_use_case_version"),
        # NULL partner_id rows are never "equal" to each other for a normal UNIQUE constraint
        # (on Postgres and SQLite alike), so global policies need their own partial unique index.
        Index("uq_policies_global_use_case_version", "use_case", "version", unique=True,
              postgresql_where=text("partner_id IS NULL"),
              sqlite_where=text("partner_id IS NULL")),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str | None] = mapped_column(ForeignKey("partners.id"), nullable=True)
    use_case: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSONType)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)


class Device(Base):
    """Phase 0: a registered signing key. Full Trusted Device Layer comes later."""

    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    public_key: Mapped[str] = mapped_column(String(64))  # Ed25519, base64url
    trust_tier: Mapped[str] = mapped_column(String(32), default="software_only")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    revoked_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class ContinuousSession(Base):
    __tablename__ = "continuous_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    use_case: Mapped[str] = mapped_column(String(100))
    policy_id: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_config: Mapped[dict] = mapped_column(JSONType)  # snapshot at start
    call_session_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    participant_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|paused|ended
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sdk_token_hash: Mapped[str] = mapped_column(String(64))
    sdk_token_expires_at_ms: Mapped[int] = mapped_column(BigInteger)


class ScoreEvent(Base):
    """One scored interval. On Postgres this table is split into one partition per day by
    `session_started_at_ms` (migration 0004, docs/adr/0015); on SQLite it stays one plain table."""

    __tablename__ = "continuous_score_events"
    # The unique index also serves every lookup by session_id (it is the leading column).
    # Postgres only allows a unique rule on a partitioned table if it includes the partition column.
    # That column is a copy of the session's start, so every row of a session has the same value and
    # the rule still means exactly "one row per session, participant and seq".
    __table_args__ = (
        UniqueConstraint("session_id", "participant_ref", "seq", "session_started_at_ms",
                         name="uq_score_events_session_participant_seq"),
    )
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("continuous_sessions.id"))
    participant_ref: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[str] = mapped_column(String(64))
    interval_start_ms: Mapped[int] = mapped_column(BigInteger)
    interval_end_ms: Mapped[int] = mapped_column(BigInteger)
    confidence_milli: Mapped[int] = mapped_column(Integer)  # as reported by the device, never altered
    # What the policy compared against its thresholds: reported minus the tier and model penalties.
    effective_confidence_milli: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[dict] = mapped_column(JSONType)
    signature: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(16))
    received_at_ms: Mapped[int] = mapped_column(BigInteger)
    # Copy of the session's started_at_ms. The partition key: never changes, set by the server.
    session_started_at_ms: Mapped[int] = mapped_column(BigInteger)


class CoverageGap(Base):
    __tablename__ = "coverage_gaps"
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("continuous_sessions.id"), index=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(32))


class WebhookEndpoint(Base):
    """A URL a partner wants events sent to. The signing secret is stored encrypted, never in clear."""

    __tablename__ = "webhook_endpoints"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # whe_...
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    event_types: Mapped[list] = mapped_column(JSONType)  # names from app/webhook_events.py, or ["*"]
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | deleted
    secret_encrypted: Mapped[str] = mapped_column(String(512))
    previous_secret_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    previous_secret_expires_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    deleted_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class WebhookOutbox(Base):
    """Every event that happened, written in the same transaction as the change that caused it
    (the "outbox" pattern), so an event is never lost and never sent for a change that rolled back."""

    __tablename__ = "webhook_outbox"
    __table_args__ = (Index("ix_webhook_outbox_fanned_out_at_ms", "fanned_out_at_ms"),)
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True)  # evt_..., what partners see
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONType)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    # NULL until the worker has turned this event into deliveries (one per subscribed endpoint).
    fanned_out_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Set only for "send test" events: deliver to this one endpoint regardless of subscriptions.
    target_endpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("webhook_endpoints.id"), nullable=True)


class WebhookDelivery(Base):
    """One event headed for one endpoint, with its retry state."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("outbox_id", "endpoint_id", name="uq_webhook_deliveries_outbox_endpoint"),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at_ms"),
        Index("ix_webhook_deliveries_partner_created", "partner_id", "created_at_ms"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # dlv_...
    outbox_id: Mapped[int] = mapped_column(BigIntId, ForeignKey("webhook_outbox.id"))
    endpoint_id: Mapped[str] = mapped_column(ForeignKey("webhook_endpoints.id"))
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|delivered|retrying|dead
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)       # attempts ever made
    failures_in_round: Mapped[int] = mapped_column(Integer, default=0)   # reset by a manual retry
    next_attempt_at_ms: Mapped[int] = mapped_column(BigInteger)
    locked_until_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # being sent now
    claim_token: Mapped[str | None] = mapped_column(String(32), nullable=True)  # who holds the lock
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(40), nullable=True)  # a short code, never text
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    delivered_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class WebhookAttempt(Base):
    """The delivery log: one row per try, with what happened. Never the partner's reply body."""

    __tablename__ = "webhook_attempts"
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("webhook_deliveries.id"), index=True)
    attempted_at_ms: Mapped[int] = mapped_column(BigInteger)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)


class SessionAttestation(Base):
    """The record of a finished call. It is created the moment the call ends. If the signer cannot be
    reached it waits here as `pending`, with its payload frozen, until it can be signed (ADR 0016)."""

    __tablename__ = "session_attestations"
    __table_args__ = (Index("ix_session_attestations_status_next", "status", "next_attempt_at_ms"),)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("continuous_sessions.id"), primary_key=True
    )
    attestation: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # {payload, signature, key_id, alg}
    issued_at_ms: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), default="signed", server_default="signed")  # signed|pending
    payload: Mapped[dict | None] = mapped_column(JSONType, nullable=True)  # unsigned, kept while pending
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signed_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AttestationKey(Base):
    """Every public key the platform has ever signed with. Rows are never deleted: an attestation
    must verify for as long as it exists, long after its key was retired."""

    __tablename__ = "attestation_keys"
    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    alg: Mapped[str] = mapped_column(String(16), default="Ed25519")
    public_key: Mapped[str] = mapped_column(String(64))  # base64url of the raw 32 bytes
    status: Mapped[str] = mapped_column(String(16))  # active | retired
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    retired_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
