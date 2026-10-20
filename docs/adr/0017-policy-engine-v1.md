# ADR 0017: Policy engine v1

- **Date:** 2026-10-19
- **Status:** Proposed (waiting for Jesutofunmi to approve; see "Open decisions")
- **Decision register / step IDs:** P0-11, ADR 0008 (the rules this implements), FR-C.8, ML architecture 2.5

## Context

ADR 0008 decided how the policy engine should behave (effective confidence, a defined fallback, immutable policy versions). Until now only the thresholds existed, a partner had no way to set them, and a device's trust tier and the on-device model version had no effect on a decision.

## Options considered

1. **Different thresholds per tier or model.** Flexible, but many numbers to tune and test.
2. **Subtract a penalty from the confidence by tier and by model version, then use one set of thresholds** (chosen in ADR 0008).
3. **For a known-defective model, treat its low scores as a reject.** Simple, but it would wrongly flag real people because of our own faulty model.

## Decision

Option 2, as ADR 0008 decided, plus:

- **Partners set policies per use case** with `POST /v1/policies`. Each change is a new, numbered, immutable version; an old version is never edited. Settings left out take their defaults. A bad policy is refused with `policy_invalid`, listing every problem at once.
- **A call keeps the policy it started with.** The call copies its settings when it starts, so a new policy version, or even a change to the stored row, cannot alter a call in progress. The attestation records the version and a fingerprint of the settings.
- **Effective confidence = reported - tier penalty - model penalty, within 0 to 1000.** The reported value is stored unchanged next to the effective one. A device with an unrecognised tier is treated as the least trusted tier. The run of low intervals that causes a reject is counted on effective values.
- **The defined fallback path (FR-C.8).** Entering `reject` is always reported to the partner by webhook, and no setting turns that off. With `fallback_behavior: flag_for_review`, entering `fallback` from `accept` (or on a first score) is reported too. Staying in a state, or moving down from `reject` to `fallback`, reports nothing new.
- **Refusing scores from a known-defective model version (ML 2.5).** `unsupported_model_versions` lists model versions whose scores are refused with 422 `model_version_unsupported`. Nothing is stored, nobody is judged, and the refused intervals appear in the attestation as missed intervals.

## Open decisions (need your answer)

1. **There is no numeric "minimum supported model version" yet.** Your build guide asks for one, but your documents do not say how model versions are named or ordered, so "older than" has no meaning. The exact-list setting above covers the real need in ML 2.5 (refuse a defective version). Once model naming is decided (P0-34), a `min_model_version` setting can be added. Tell me if you want it sooner and what the version names look like.
2. **Policy creation is not audit-logged yet.** The spec requires it; the audit log is step P0-13.
3. **Not built, still on hold:** participant visibility of other people's status (D-17), and the `session.confidence_recovered` event that ADR 0008 only proposed.

## Consequences

Numbers remain placeholders until the edge benchmark. A partner can create any number of policy versions (there is no cap yet; the existing API rate limits apply). The new column `effective_confidence_milli` means a score's decision can always be reproduced and explained later. `GET /v1/sessions/.../status` now shows both values.
