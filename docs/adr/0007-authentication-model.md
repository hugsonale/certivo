# ADR 0007: Authentication model: scoped keys, short-lived SDK tokens, and what Tier 3 means

- **Date:** 2026-10-11
- **Status:** Accepted (Tier 3 meaning needs privacy review in P0-52)
- **Decision register / step IDs:** P0-05, P0-06, P0-10, D-05

## Context

Build Spec 0 used one kind of partner key and one session token with no expiry or scopes. The suite also defines a Tier 3 trust level using a "Device Trust Service" and device fingerprinting that does not exist.

## Options considered

1. **Keep one all-powerful key:** simplest, but one leak exposes everything.
2. **Scoped keys, several per partner, immediate revocation, plus a time-limited per-session SDK token.**
3. **Build the fingerprinting Device Trust Service the suite describes for Tier 3:** matches the text, but adds a tracking-risk feature before it is needed.

## Decision

Option 2 for credentials: keys carry scopes, are stored only as hashes, are revoked immediately with no cache, and rotate by creating a new key before revoking the old. SDK tokens work for one session only, expire (placeholder 6 hours) and cannot read or end sessions. Published platform keys keep retired keys forever so old attestations still verify. For Tier 3 we **do not** build fingerprinting: **Tier 3 means only a registered software-held key.**

## Consequences

Phase 0 keeps working because existing keys behave as all-scopes until P0-06. Tier 3 devices are less trusted and the policy can weigh that. Because Tier 3 is defined more narrowly than the Technical Requirements Document, that document's Table 8.1 needs a note. The privacy review (P0-52) may later approve limited signals.
