# 07. Implausible-pattern detection

Status: P0-12. Source requirement: Technical Requirements Document 9.4, Security Architecture 4.3.

A device that fakes or replays scores tends to produce a pattern a genuine device does not. The platform
watches for four such patterns and raises a **flag**: an internal security signal, kept apart from a normal
low-confidence result, for the incident-response process.

## 1. The rule that matters most: flag only, never block

In Phase 0 a flag **never** changes an outcome, rejects or delays a packet, sends a webhook, appears in the
partner API, or appears in an attestation. Detection runs **after** a packet is saved, in its own step, so a
failure inside it cannot undo or reject an upload. It can be switched off with
`CERTIVO_ANOMALY_DETECTION_ENABLED=false`.

## 2. The patterns

Each is judged over a participant's latest **30** scores (30 seconds of a real call). Nothing is judged on
fewer. All numbers are **placeholders** to be tuned on real device data (P0-33 to P0-40).

| Flag | Raised when | Why it is suspicious |
|---|---|---|
| `flat_maximum_confidence` | Every one of the 30 scores is 990 or above and the highest and lowest differ by at most 5 | A real model's output moves; a forged "always perfect" score does not |
| `impossible_score_jumps` | At least 3 jumps of 900 or more between neighbouring scores within the 30 | A face cannot appear and vanish again and again, second after second. One dip (a hand over the camera) is two jumps and is not flagged |
| `faster_than_real_time` | The 30 packets arrived within 25% of the time they claim to cover | A real device cannot produce a minute of scores in a few seconds; a replay can |
| `zero_timing_jitter` | The gaps between the 30 arrivals all agree to within 1 ms | Real networks have jitter |

* The two timing patterns are judged **only on packets sent live**, never on packets uploaded after an
  outage (`received_via` is `batch`), which arrive in a burst on purpose (ADR 0014). They are also skipped if
  a packet is missing inside the window.
* A flag is raised **once per kind, per participant, per session**, not on every later packet.
* On the live path the check runs on every 10th packet once the window is full; after a batch upload it runs
  once for each participant in the batch.

## 3. What is recorded

Table `security_flags`: session, partner, participant, device, flag type, small facts (counts and
milliseconds, no scores), the first and last `seq` examined, and the time. There is deliberately **no**
unique rule on it, so recording a flag can never fail an upload. Each flag is also written to the log
(`certivo.security`). To read them: `python scripts/list_flags.py`.

## 4. Not built yet

* The third TRD 9.4 pattern, **a device starting an unusually high number of sessions across different
  accounts**, needs an index by device that the score-events table does not have. It belongs with the
  analytics work (P0-13, P1-11).
* Showing partners a summary of flags, and acting on a flag, are decisions for later phases (ADR 0018).
* No retention rule exists for flags yet; it waits for the privacy review (P0-52).
