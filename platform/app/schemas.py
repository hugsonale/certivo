from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, field_validator

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
