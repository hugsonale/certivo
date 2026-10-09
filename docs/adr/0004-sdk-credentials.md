# ADR 0004: Partner API keys and per-session SDK tokens

- **Date:** 2026-10-09
- **Status:** Accepted for Phase 0
- **Decision register / step IDs:** D-05, P0-06

## Context

The SDK ships inside partner apps that run on end users' devices. Anything inside it can be extracted, so it must never hold a partner's secret API key.

## Options considered

1. **Put the partner API key in the SDK:** simple, unsafe.
2. **Publishable key plus per-session token:** the standard safe pattern, more to build.
3. **Partner API key for server-to-server calls, and a short per-session token handed to the client when a session starts:** works now, and can grow into option 2.

## Decision

Option 3. Partner endpoints use a partner API key (`cvk_...`). Starting a session returns a one-time SDK token (`skt_...`) used only for that session's SDK endpoints. Both are stored only as SHA-256 hashes.

## Consequences

The partner's own backend must start the session and pass the token to its client. SDK tokens do not yet expire or get revoked mid-session; step P0-06 adds a time limit and revocation. A publishable-key flow for self-serve onboarding is planned for Phase 2.
