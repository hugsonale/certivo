"""API key scopes (docs/spec/base/02-authentication-and-keys.md, section 2)."""
from __future__ import annotations

from typing import Literal

Scope = Literal[
    "sessions:write", "sessions:read",
    "devices:write", "devices:read",
    "policies:write", "policies:read",
    "webhooks:write", "webhooks:read",
    "consents:write", "consents:read",
    "audit:read", "analytics:read",
    "keys:admin",
]

ALL_SCOPES: tuple[str, ...] = (
    "sessions:write", "sessions:read",
    "devices:write", "devices:read",
    "policies:write", "policies:read",
    "webhooks:write", "webhooks:read",
    "consents:write", "consents:read",
    "audit:read", "analytics:read",
    "keys:admin",
)
