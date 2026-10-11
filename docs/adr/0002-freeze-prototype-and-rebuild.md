# ADR 0002: Freeze the prototype and rebuild on a new branch

- **Date:** 2026-10-09 (recorded after the fact; the work was done earlier in October 2026)
- **Status:** Accepted
- **Decision register / step IDs:** P0-01

## Context

The original code was a point-in-time, challenge-based liveness prototype that processed video on the server. The 18-document suite instead specifies continuous, on-device verification of live calls, with only signed score packets reaching the backend. The two designs differ at the root, so very little of the old code carries over.

## Options considered

1. **Evolve the old code toward the new design:** keeps history in one place, but drags along a large amount of structure that does not fit.
2. **Start a separate repository:** clean, but loses the link to existing history and CI.
3. **Freeze the old code under a tag and build on a new `rebuild` branch, keeping only reference material:** clean working tree, old code still recoverable.

## Decision

Option 3. The old state is tagged `legacy-liveness-v0`. The `rebuild` branch holds `platform/`, `sdk-web/`, `demo-call/`, `docs/spec/`, and a reference-only `legacy/` folder containing the modules most likely to be ported. Everything else was removed from the branch and remains available from the tag.

## Consequences

New code must not import from `legacy/`; modules are moved out and adapted when ported. The old repository history may still contain secrets, so those must be rotated and, optionally, purged from history. The old CI workflows are parked under `legacy/ci/` and are not active; new CI lives in `.github/workflows/`.
