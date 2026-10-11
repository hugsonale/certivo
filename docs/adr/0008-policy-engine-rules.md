# ADR 0008: Policy engine rules: effective confidence, fallback behaviour, visibility

- **Date:** 2026-10-11
- **Status:** Accepted for the implemented settings; Proposed for visibility
- **Decision register / step IDs:** P0-05, P0-11, D-17

## Context

The suite says a per-interval policy engine "unchanged" from point-in-time verification applies. No such engine existed. We also need the engine to honour PRD FR-C.8 (never silently ignore a drop), weigh device trust, and cope with weak model versions.

## Options considered

1. **Different thresholds per tier or model:** flexible, but many settings to tune and test.
2. **Subtract a penalty from the confidence by tier and by model version, then use one set of thresholds.**
3. **Hard-code one behaviour:** simple, but partners differ (dating, meetings, livestreams).

## Decision

Option 2. The raw confidence is never altered or hidden; both raw and effective values are stored. Entering `reject` always raises an event; borderline results raise one only when the partner sets `flag_for_review`. Policies are immutable versions, and a session keeps the version it started with. We propose a `participant_visibility` setting and a `peers` endpoint so participants' apps can show each other's status.

## Consequences

Numbers stay placeholders until the edge benchmark. A new event `session.confidence_recovered` is proposed. The visibility proposal (D-17) needs your decision before it is built.
