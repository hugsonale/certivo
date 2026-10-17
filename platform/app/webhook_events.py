"""The webhook event catalogue (docs/spec/base/05-webhooks.md, section 5).

`EVENT_TYPES` are the events a partner can subscribe to. Some cannot be emitted yet because the
feature behind them arrives in a later build step; partners can subscribe now and will start
receiving them when it lands. `webhook.test` is separate: it is only ever sent by the "send test"
button, to the one endpoint that asked for it.
"""
from __future__ import annotations

EVENT_TYPES: dict[str, str] = {
    "session.confidence_dropped": "A participant entered reject (or fallback, when the policy flags it)",
    "session.paused": "Verification became unavailable for a session",
    "consent.withdrawn": "Consent was withdrawn (arrives with step P0-51)",
    "device_switch.detected": "An account tried a session from a different device (arrives with P1-06)",
    "trusted_device.revoked": "A Trusted Device Token was revoked (arrives with P1-02)",
}
TEST_EVENT = "webhook.test"
ALL_EVENT_TYPES = (*EVENT_TYPES, TEST_EVENT)
API_VERSION = "v1"
