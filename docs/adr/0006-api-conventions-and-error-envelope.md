# ADR 0006: API conventions and one error shape

- **Date:** 2026-10-11
- **Status:** Accepted
- **Decision register / step IDs:** P0-05

## Context

The suite refers to a standard error schema and REST conventions "from Version 1.0" that never existed. Partners need one predictable way to handle failures, and an unexpected crash was returning plain text.

## Options considered

1. **Let each endpoint choose its own errors:** fast, but partners cannot write general handling.
2. **Copy a well-known public API's error format:** familiar, but imports details we do not need.
3. **One small envelope with stable machine-readable codes, and a catalogue kept equal to the code by a test.**

## Decision

Option 3. Every error has `error.code`, `message`, `request_id` and optional `details`. The `code` is the contract and never changes meaning; `message` may be reworded. Unknown and revoked credentials look identical. Unexpected crashes use the same shape (`internal_error`) and reveal nothing. Conventions for times, scores, IDs, paging, idempotency and rate limiting are written in one place (base/01).

## Consequences

Partners switch on `code`. Adding a code needs a catalogue row, and a test fails if code and catalogue differ. Planned codes (rate limiting, scopes, consent) are reserved now so they will not collide later. Idempotency keys are only proposed, not decided.
