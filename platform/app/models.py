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
    """Phase 0 plain table. Daily partitioning (Database Design doc) is a later migration."""

    __tablename__ = "continuous_score_events"
    # This unique index also serves every lookup by session_id (it is the leading column).
    __table_args__ = (
        UniqueConstraint("session_id", "participant_ref", "seq",
                         name="uq_score_events_session_participant_seq"),
    )
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("continuous_sessions.id"))
    participant_ref: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[str] = mapped_column(String(64))
    interval_start_ms: Mapped[int] = mapped_column(BigInteger)
    interval_end_ms: Mapped[int] = mapped_column(BigInteger)
    confidence_milli: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[dict] = mapped_column(JSONType)
    signature: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(16))
    received_at_ms: Mapped[int] = mapped_column(BigInteger)


class CoverageGap(Base):
    __tablename__ = "coverage_gaps"
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("continuous_sessions.id"), index=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(32))


class WebhookOutbox(Base):
    """Phase 0 records events only. A delivery worker is a later task."""

    __tablename__ = "webhook_outbox"
    id: Mapped[int] = mapped_column(BigIntId, primary_key=True, autoincrement=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONType)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    delivered_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class SessionAttestation(Base):
    __tablename__ = "session_attestations"
    session_id: Mapped[str] = mapped_column(
        ForeignKey("continuous_sessions.id"), primary_key=True
    )
    attestation: Mapped[dict] = mapped_column(JSONType)  # {payload, signature, key_id, alg}
    issued_at_ms: Mapped[int] = mapped_column(BigInteger)
