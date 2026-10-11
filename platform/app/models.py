from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    pass


class Partner(Base):
    __tablename__ = "partners"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at_ms: Mapped[int] = mapped_column(BigInteger)


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex
    key_prefix: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)


class Policy(Base):
    """partner_id NULL = global default available to every partner."""

    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("partner_id", "use_case", "version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str | None] = mapped_column(ForeignKey("partners.id"), nullable=True)
    use_case: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    config: Mapped[dict] = mapped_column(JSON)
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


class ContinuousSession(Base):
    __tablename__ = "continuous_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    use_case: Mapped[str] = mapped_column(String(100))
    policy_id: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_config: Mapped[dict] = mapped_column(JSON)  # snapshot at start
    call_session_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    participant_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|paused|ended
    started_at_ms: Mapped[int] = mapped_column(BigInteger)
    ended_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sdk_token_hash: Mapped[str] = mapped_column(String(64))


class ScoreEvent(Base):
    """Phase 0 plain table. Daily partitioning (Database Design doc) is a later migration."""

    __tablename__ = "continuous_score_events"
    __table_args__ = (
        UniqueConstraint("session_id", "participant_ref", "seq"),
        Index("ix_score_events_session", "session_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"),
                                    primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("continuous_sessions.id"))
    participant_ref: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[str] = mapped_column(String(64))
    interval_start_ms: Mapped[int] = mapped_column(BigInteger)
    interval_end_ms: Mapped[int] = mapped_column(BigInteger)
    confidence_milli: Mapped[int] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(64))
    explanation: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(16))
    received_at_ms: Mapped[int] = mapped_column(BigInteger)


class CoverageGap(Base):
    __tablename__ = "coverage_gaps"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"),
                                    primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("continuous_sessions.id"), index=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(32))


class WebhookOutbox(Base):
    """Phase 0 records events only. A delivery worker is a later task."""

    __tablename__ = "webhook_outbox"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"),
                                    primary_key=True, autoincrement=True)
    partner_id: Mapped[str] = mapped_column(ForeignKey("partners.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    delivered_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class SessionAttestation(Base):
    __tablename__ = "session_attestations"
    session_id: Mapped[str] = mapped_column(
        ForeignKey("continuous_sessions.id"), primary_key=True
    )
    attestation: Mapped[dict] = mapped_column(JSON)  # {payload, signature, key_id, alg}
    issued_at_ms: Mapped[int] = mapped_column(BigInteger)
