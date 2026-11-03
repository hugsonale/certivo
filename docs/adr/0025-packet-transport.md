# 0025. Packet transport: order, retries, buffering, pause and resume, telemetry (P0-25)

**Date:** 3 November 2026
**Status:** Proposed

## Context

ADR 0014 gave the platform a batch endpoint and per-packet results, and left "the SDK's own buffer size and retry timing" to this step.
Build Spec 0 section 4 sets the rules the SDK must live with: `seq` must increase; the same `seq` with the same signature is a safe repeat (`duplicate: true`); the same `seq`
with a different signature is `409 seq_conflict`; a lower `seq` than one already taken is `409 seq_out_of_order`; time may not go backwards; a valid packet while paused ends the pause.
Only the batch endpoint tells the platform that scores were late, so only a packet sent through it can show up in the attestation as a `delayed_upload` gap.
Before this step the pipeline sent each packet itself and, on a network error, put it in a buffer that nothing ever emptied.

## Decision (proposed)

1. **One owner: `PacketSender`** (`packages/core/src/sender.ts`). The pipeline hands it signed packets and gets back one answer per packet: `sent`, `buffered`, `dropped` or `stopped`. It never throws and never holds up the call.
2. **Order is kept by sending one request at a time, oldest first.** A packet is tried straight away on the single-packet endpoint. If that fails for a reason worth retrying, it waits, and every newer packet queues behind it.
   Because only one request is ever in flight, the network cannot reorder them. Packets handed over out of order while waiting are sorted by `seq` before upload.
3. **A packet that had to wait goes up on the batch endpoint**, at most 25 at a time, oldest first, even if it is alone. This is what lets the platform disclose the delay honestly.
4. **A lost reply is safe.** The retry comes back `duplicate: true`, which the sender counts as success. A double delivery by the network does the same.
5. **Retries** wait 0.5 s, then twice as long each time up to 30 s, with jitter (between half and all of the wait). A `Retry-After` from the platform is obeyed, up to 120 s. A success resets the wait. These numbers are placeholders, not measured.
6. **What is retried and what is not.** Retried: no network, 5xx, 429, and anything unexpected. Dropped for good, counted and reported: `seq_conflict`, `seq_out_of_order`, `non_monotonic_interval`, `invalid_interval`, `timestamp_in_future`, `non_canonical_payload`, `validation_error`, and a bad packet signature.
   Stop for good, and tell the app: token expired or refused, session ended, session not found. A refused request that is too big (413), or a whole batch refused as malformed (422), is split in half until the bad packet is alone and only it is dropped.
7. **The buffer is bounded** (600 packets, about 30 minutes at 3 s). When full the OLDEST packet is thrown away and counted; the platform discloses the hole as a `missing_packets` gap (ADR 0014).
8. **Pause and resume.** `pause(reason)` tells the platform once. It is best effort and is NOT queued: a pause that arrives late would put the gap in the wrong place, and the platform finds a hole in the packets by itself anyway.
   `resume()` is only needed when no packet is about to follow, because a packet that gets through ends the pause (Spec 0). The pipeline pauses by itself after 3 intervals in a row with no score (`model_unavailable` if the model never loaded, otherwise `sdk_error`), once per streak. The 3 is a placeholder.
9. **Sequence numbers** come from the sender (`nextSeq()`). A `SeqStore` can remember the next number across a page reload, so a reload in the middle of a call carries on instead of starting at 0 and being refused as `seq_out_of_order`.
   `TabSeqStore` keeps ONE whole number per session in the browser's per-tab storage (gone when the tab closes). The default remembers nothing; the partner turns it on by passing `new TabSeqStore(window.sessionStorage)`.
10. **Telemetry** (`sender.telemetry()`) is plain counters: submitted, confirmed, sent directly, uploaded from the buffer, duplicates acknowledged, retries, rate limits, batches, splits, buffer size and high-water mark, drops by reason, pauses and resumes, current backoff, last success. Numbers and short code words only: never a score, a token or a participant.
11. **The pipeline fix that came with it.** An interval used to start where the last good one ended. After a long run with no score it would stretch past the 60-second limit and every later packet would fail for good. A new interval now starts one interval back when the last good one is older than 1.5 intervals; the hole is left for the platform to disclose.
    `IntervalOutcome` gained `dropped` and `stopped`. The old `send` and `buffer` options still work when no `sender` is given.

## Fault injection

`packages/core/test/fake-platform.ts` follows the Spec 0 rules and can lose a request, lose a reply, deliver twice, answer 5xx or 429, refuse an oversized or malformed batch, and go down for a while.
`sender.test.ts` breaks one thing at a time. `fault-injection.test.ts` breaks everything at random under 50 fixed seeds and checks that the platform never sees a packet out of order or in conflict, every packet is accepted exactly once and in order,
nothing is left waiting once the network is back, and every packet is accounted for even when the buffer overflows. A real-browser test (`e2e/no-media-egress.spec.ts`) takes the platform down for three requests in the middle of a call and checks recovery, order, and that the batch upload passes the same leak rules as everything else.

## Consequences

- Delivery is now defined for lost, duplicated and delayed packets. A packet that was ALREADY accepted before a higher one cannot be reordered by the sender (it is dropped as `seq_out_of_order`); the pipeline never produces one.
- **Not done, deliberately:**
  - Waiting packets are NOT written to disk. They hold a person's scores, and how long such data may stay on a device is the privacy review's call (P0-52). A reload loses the packets still waiting; the platform shows the hole as a gap.
  - There is no token refresh: Spec 0 has no endpoint for it. When the token expires the sender stops and emits `stopped: token_expired` so the partner's app can react.
  - Telemetry is not sent anywhere: Spec 0 has no endpoint for it and I did not have TRD 2.6 to check what it asks for. The partner's app can read or forward the counters. An endpoint belongs with P1-16.
- **To confirm against `platform/app/services/sessions.py`** (I did not have it): whether a late BATCH accepted while the session is paused ends the pause the way a single packet does. The Spec says only "a valid packet".
- `TabSeqStore` adds one small item to the data inventory (P0-52): a whole number per session, tab-scoped.

## Related

P0-08 and ADR 0014, ADR 0022 (packet), ADR 0024 (capture), Build Spec 0 sections 2, 4 and 5, guide steps P0-25, P0-52 and P1-16.
