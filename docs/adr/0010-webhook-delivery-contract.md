# ADR 0010: Webhook delivery contract

- **Date:** 2026-10-11
- **Status:** Accepted
- **Decision register / step IDs:** P0-05, P0-07

## Context

Events are already written to an outbox table but nothing delivers them, and the suite does not say how a partner can trust or de-duplicate a message.

## Options considered

1. **Plain unsigned POST:** simple, but anyone can forge it.
2. **Signed (HMAC) messages with a timestamp, retries, and de-duplication by ID.**
3. **A pull-only API:** safe, but partners want to be told.

## Decision

Option 2. Messages are signed with a per-endpoint secret over the timestamp and raw body; receivers reject old timestamps and compare in constant time. Delivery is at-least-once with no ordering promise; receivers de-duplicate by event ID. Retries back off over about a day, then a delivery is `dead` until retried by hand. URLs must be public HTTPS, to stop our servers being used to probe internal networks. Payloads hold IDs and small numbers only.

## Consequences

Timings are placeholders. Secrets must be stored encrypted because we must be able to sign with them. A shared test vector fixes the signing scheme across languages.
