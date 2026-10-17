# ADR 0014: Buffered upload and honest gap disclosure

- **Date:** 2026-10-16
- **Status:** Proposed (waiting for Jesutofunmi to approve)
- **Decision register / step IDs:** P0-08, P0-25 (the SDK half comes later)

## Context

The System Design Document (section 7.1) says that when the backend cannot be reached during a call, the SDK keeps scoring and buffers signed packets, then uploads them with their original timestamps. If the outage is long, the attestation must say so rather than present the session as continuously verified. Until now the server could only take one packet at a time and recorded gaps only when the SDK paused.

## Options considered

1. **Accept late packets silently:** the history is complete, but the partner never learns they had no live signal during the outage.
2. **Treat every late packet as lost:** honest about the live signal, but throws away real evidence.
3. **Keep the packets and disclose the period as a gap, with a reason that says the scores arrived late.**
4. **Batch is all-or-nothing:** simple, but one bad packet would throw away a whole outage's worth of good ones.

## Decision

Option 3, with per-packet results.

- `POST .../score-events/batch` takes 1 to 25 packets, oldest first. Each packet goes through exactly the same checks as a single packet (signature, interval, duplicate, order), so a bad packet is reported by position and the good ones are kept. Everything accepted and every gap it reveals are saved in one transaction.
- Re-sending a batch is safe: packets already stored come back as `duplicate` and add no second gap.
- A newly accepted packet that arrives more than `gap_disclosure_threshold_ms` after its interval ended records one `delayed_upload` gap, from the start of the oldest such interval to the moment we received it.
- A hole longer than the threshold between two of a participant's consecutive packets records a `missing_packets` gap (the SDK buffer overflowed and the oldest scores were dropped).
- A gap already covered by an existing one (for example an explicit pause) is not recorded twice, and overlapping gaps are counted once in `paused_ms`.
- Only the batch endpoint discloses delays. A single packet sent normally is not judged.

## Consequences

`coverage_milli` measures live coverage, so a session with a long outage reports less than 1000 even though every score was recovered. The attestation's shape is unchanged: only two new gap reasons exist. The threshold (10 seconds) is a placeholder to be set from measured outages. The limit of 25 packets per batch means even maximum-size packets (about 1.8 KB each) fit the 64 KiB body limit; a 40-second outage is uploaded as two batches. A malformed packet (wrong type or range) still refuses the whole request as a validation error, because the SDK builds packets itself and a malformed one is a bug to fix, not an outage to ride out. The SDK's own buffer size and retry timing are decided in P0-25.
