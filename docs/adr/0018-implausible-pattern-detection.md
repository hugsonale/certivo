# ADR 0018: Implausible-pattern detection

- **Date:** 2026-10-20
- **Status:** Proposed (waiting for Jesutofunmi to approve; see "Open decisions")
- **Decision register / step IDs:** P0-12, TRD 9.4, Security Architecture 4.3

## Context

The score comes from a device Certivo does not control, so a modified SDK could claim a false, high score. The signed packet and the device trust tier are two defences. The third is statistical: a forged or replayed stream tends to look different from genuine behaviour. TRD 9.4 asks that such patterns be flagged as security signals, separate from a normal low-confidence rejection. Your guide adds: flag only, never block, in Phase 0.

## Options considered

1. **Reject suspicious packets.** Stops some attacks, but any false alarm would reject a real person.
2. **Lower the score of a suspicious device** through the policy engine. Quieter, but still changes decisions on weak evidence.
3. **Raise an internal flag and change nothing.** Gathers evidence safely while the thresholds are still guesses.

## Decision

Option 3.

- Four patterns: `flat_maximum_confidence`, `impossible_score_jumps`, `faster_than_real_time`, `zero_timing_jitter`, each judged over a participant's latest 30 scores (docs/spec/base/07-implausible-patterns.md). The numbers are placeholders.
- **Detection runs after the upload is saved, in its own step.** A bug or database error inside it cannot reject, delay or undo an upload. It can also be switched off.
- **Each score records how it arrived** (`live` or `batch`). Timing patterns count only live packets, because an upload after an outage legitimately arrives in a burst (ADR 0014).
- **Flags are internal.** They are stored in `security_flags`, logged, and readable with `scripts/list_flags.py`. They never appear in the partner API, the attestation or a webhook, and nothing acts on them yet.
- **No unique rule on flags**, so recording one can never fail an upload.

## Open decisions (need your answer)

1. **Should partners ever see flags?** Showing which pattern was noticed would help a partner investigate, but it would also tell an attacker exactly what to avoid. I kept flags internal.
2. **The thresholds are guesses.** They are set so that a genuine session does not trip them. Before any flag is allowed to influence a decision, they must be tuned on real device data from the edge benchmark.
3. **The third TRD pattern** (many sessions from one device across accounts) is not built; it needs an index by device (see the spec, section 4).

## Consequences

No extra database work happens until 30 scores exist; after that there is one small indexed read on every 10th live packet. Revisit in the load test (P0-13). A simulator that sends 30 or more packets in a burst (for example a long run of `sandbox_call.py`) will flag itself as a replay, by design. The shipped 12-packet demo does not. Flags have no retention rule yet (P0-52).
