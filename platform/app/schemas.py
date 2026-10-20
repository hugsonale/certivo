from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator

from app.scopes import Scope

Ref = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
Code = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,48}$")]
_SIGNAL_KEY = re.compile(r"^[a-z0-9_]{1,48}$")


class SessionStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_case: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]
    call_session_reference: Annotated[
        str, StringConstraints(pattern=r"^[\x20-\x7e]{1,128}$")] | None = None
    participant_count: StrictInt = Field(default=1, ge=1, le=1000)


class SessionStartOut(BaseModel):
    id: str
    status: str
    re_evaluation_interval_ms: int
    sdk_token: str  # shown once; give to the SDK, never log it
    sdk_token_expires_at_ms: int


class ExplanationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_codes: list[Code] = Field(min_length=1, max_length=8)
    signal_milli: dict[str, StrictInt] = Field(default_factory=dict)

    @field_validator("signal_milli")
    @classmethod
    def _signals(cls, v: dict[str, int]) -> dict[str, int]:
        if len(v) > 16:
            raise ValueError("at most 16 signals")
        for k, val in v.items():
            if not _SIGNAL_KEY.match(k) or not 0 <= val <= 1000:
                raise ValueError("signal keys must match [a-z0-9_]{1,48}, values 0..1000")
        return v


class ScoreEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1]
    participant_reference: Ref
    device_id: Annotated[str, StringConstraints(pattern=r"^dev_[0-9a-f]{32}$")]
    seq: StrictInt = Field(ge=0, le=2**31 - 1)
    interval_start_ms: StrictInt = Field(ge=0)
    interval_end_ms: StrictInt = Field(ge=0)
    confidence_milli: StrictInt = Field(ge=0, le=1000)
    model_version: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]
    explanation: ExplanationIn
    device_signature: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{86}$")]

    def signed_payload(self, session_id: str) -> dict:
        """The exact object the device signed (see BUILD_SPEC_0 section 4)."""
        payload = self.model_dump(exclude={"device_signature"})
        payload["session_id"] = session_id
        return payload


class ScoreEventOut(BaseModel):
    accepted: bool
    seq: int
    current_policy_outcome: str
    duplicate: bool = False


MAX_BATCH_PACKETS = 25  # even 25 maximum-size packets (about 1.8 KB each) fit the 64 KiB body limit


class ScoreBatchIn(BaseModel):
    """Packets the SDK buffered while it could not reach us, oldest first."""

    model_config = ConfigDict(extra="forbid")
    packets: list[ScoreEventIn] = Field(min_length=1, max_length=MAX_BATCH_PACKETS)


class BatchItemError(BaseModel):
    code: str
    message: str


class BatchItemOut(BaseModel):
    index: int  # position in the request, starting at 0
    accepted: bool
    seq: int
    current_policy_outcome: str | None = None
    duplicate: bool = False
    error: BatchItemError | None = None  # set only when accepted is false


class ScoreBatchOut(BaseModel):
    results: list[BatchItemOut]
    accepted_count: int  # newly recorded
    duplicate_count: int  # already recorded earlier (a safe retry)
    rejected_count: int
    gaps_recorded: int  # coverage gaps this batch added to the session


class PauseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["connectivity", "sdk_error", "model_unavailable", "other"] = "other"


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]


class DeviceOut(BaseModel):
    id: str
    trust_tier: str
    status: str
    created_at_ms: int


class ApiKeyCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9 _.:-]{1,100}$")]
    scopes: list[Scope] = Field(min_length=1, max_length=13)

    @field_validator("scopes")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("scopes must not repeat")
        return v


class ApiKeyOut(BaseModel):
    id: str
    name: str
    scopes: list[str]
    key_prefix: str
    active: bool
    created_at_ms: int
    last_used_at_ms: int | None = None
    revoked_at_ms: int | None = None


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # the full key: shown once, never again


EventName = Literal["*", "session.confidence_dropped", "session.paused", "consent.withdrawn",
                    "device_switch.detected", "trusted_device.revoked"]
DeliveryStatus = Literal["pending", "delivered", "retrying", "dead"]


class WebhookEndpointCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: Annotated[str, StringConstraints(min_length=8, max_length=2048)]
    event_types: list[EventName] = Field(min_length=1, max_length=6)
    description: Annotated[str, StringConstraints(pattern=r"^[\x20-\x7e]{1,200}$")] | None = None

    @field_validator("event_types")
    @classmethod
    def _tidy(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("event_types must not repeat")
        return ["*"] if "*" in v else v  # "everything" makes any other choice redundant


class WebhookEndpointOut(BaseModel):
    id: str
    url: str
    event_types: list[str]
    description: str | None = None
    status: str
    created_at_ms: int


class WebhookEndpointCreatedOut(WebhookEndpointOut):
    secret: str  # the signing secret: shown once, never again


class WebhookSecretRotatedOut(BaseModel):
    id: str
    secret: str  # shown once
    previous_secret_valid_until_ms: int


class WebhookAttemptOut(BaseModel):
    attempted_at_ms: int
    status_code: int | None = None
    error: str | None = None
    duration_ms: int


class WebhookDeliveryOut(BaseModel):
    id: str
    event_id: str
    event_type: str
    endpoint_id: str
    status: DeliveryStatus
    attempt_count: int
    next_attempt_at_ms: int | None = None  # only while pending or retrying
    last_status_code: int | None = None
    last_error: str | None = None
    created_at_ms: int
    delivered_at_ms: int | None = None
    attempts: list[WebhookAttemptOut] = []  # the most recent tries, newest first


class PolicyCreateIn(BaseModel):
    """Settings left out take their defaults (docs/spec/base/03-policy-engine.md). They are checked by the
    policy engine rather than here, so that every problem is reported at once in `policy_invalid`."""

    model_config = ConfigDict(extra="forbid")
    use_case: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]
    settings: dict = Field(default_factory=dict)


class PolicyOut(BaseModel):
    id: str
    use_case: str
    version: int
    owner: str  # "partner" for your own policies, "certivo" for the built-in default
    settings: dict  # every setting, explicit
    settings_sha256: str  # the fingerprint written into an attestation, so you can match them up
    created_at_ms: int
