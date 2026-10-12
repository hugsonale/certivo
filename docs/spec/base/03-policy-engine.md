# 03. Policy engine

## In plain words

Every few seconds a device reports how confident it is that the person on the call is real and unaltered.
The policy engine turns that number into a simple decision for each participant: **accept** (all fine),
**fallback** (borderline, keep an eye on it) or **reject** (confidence has dropped). A partner chooses the
thresholds and what should happen. The same inputs always give the same decision, which is what makes
sandbox testing possible. The engine never sees video, audio or faces; it only sees numbers and reason codes.

## 1. Partner settings

A policy is a small set of settings, identified by a `use_case` name (for example `default_video_call`).
Settings are whole numbers or short ASCII strings only, because a fingerprint of the settings is signed into
every attestation.

| Setting | Type | Meaning | Default | Status |
|---|---|---|---|---|
| `re_evaluation_interval_ms` | integer, at least 100 | How often the SDK should report a score | 1000 (placeholder) | Implemented |
| `accept_min_milli` | integer 0 to 1000 | Effective confidence at or above this is `accept` | 700 (placeholder) | Implemented |
| `reject_below_milli` | integer 0 to `accept_min_milli` | Effective confidence below this counts toward `reject` | 400 (placeholder) | Implemented |
| `drop_consecutive` | integer, at least 1 | How many low intervals in a row make `reject` | 2 (placeholder) | Implemented |
| `fallback_behavior` | `indicator_only` or `flag_for_review` | What a `fallback` result triggers. `indicator_only` changes the status only; `flag_for_review` also sends a webhook | `indicator_only` | Planned (P0-11) |
| `tier_penalty_milli` | object with `hardware_attested`, `platform_authenticated`, `software_only`, each 0 to 1000 | Subtracted from the confidence before comparing, by the device's trust tier | all 0 | Planned (P0-11) |
| `model_penalties` | list of up to 16 items `{model_version, penalty_milli}` | Subtracted from the confidence for a named, known-weak model version | empty list | Planned (P0-11) |
| `participant_visibility` | `none`, `outcome`, `outcome_and_reasons` or `full` | What participants may see about each other (section 5) | `outcome_and_reasons` | Proposed |

**All numeric defaults are placeholders**, chosen only so the pipeline can be tested. Real thresholds come
from the edge-model benchmark (Master Build Guide, P0-33 to P0-40), not from guessing now.

## 2. How a decision is made

For each participant, each time a valid score packet arrives:

1. **Effective confidence** = the reported confidence, minus the tier penalty for that device's trust tier,
   minus the penalty for that packet's model version (if listed), never below 0 or above 1000. Today both
   penalties are zero, so effective equals reported. The **reported value is never altered or hidden**; both
   values are stored.
2. **Band:**
   - at or above `accept_min_milli` → `accept`
   - from `reject_below_milli` up to (not including) `accept_min_milli` → `fallback`
   - below `reject_below_milli` → `fallback` for the first low interval, and `reject` once
     `drop_consecutive` low intervals have occurred in a row (counting this one)
3. A single good interval ends a run of low ones immediately.
4. The decision is stored with the packet and returned as `current_policy_outcome`.

Worked example with the defaults (accept at 700, reject below 400, two in a row):

| Interval | Confidence | Decision | Why |
|---|---|---|---|
| 1 | 930 | accept | at or above 700 |
| 2 | 150 | fallback | low, but only one in a row |
| 3 | 140 | reject | second low in a row |
| 4 | 900 | accept | a good interval ends the run |

## 3. What each decision triggers

| Decision | What the partner sees | Webhook |
|---|---|---|
| `accept` | Normal status | none |
| `fallback` | Status shows `fallback` (borderline); the in-call indicator shows the warning treatment | `session.confidence_dropped` with `outcome: fallback`, **only** if `fallback_behavior` is `flag_for_review` (Planned, P0-11) |
| `reject` | Status shows `reject`; the partner's configured response applies (private prompt, visible warning, or silent moderator flag; Design System section 6.3) | `session.confidence_dropped` with `outcome: reject`, **always**, once each time a participant enters `reject` (Implemented; the `outcome` field is added in P0-11) |
| back to `accept` after `reject` | Status returns to normal | `session.confidence_recovered` (Proposed) |

A drop is **never silently ignored** (PRD FR-C.8): entering `reject` always produces an event and an audit
entry, and no setting turns that off. A partner can set the thresholds, but any threshold crossing that
the policy defines is reported.

**Pausing is not a decision.** A session that cannot be verified because of a connectivity problem is
`paused`, a state of the session, never of the person (PRD NFR-2.2). It is never reported as `accept` and never
as `reject`.

## 4. Managing policies

1. Policies are **immutable versions**. Changing settings creates a new version; old versions are never edited.
2. A session **keeps the version it started with**, so changing a policy never alters a call in progress. The
   version and a fingerprint of the settings are written into the attestation.
3. A partner's own policy for a `use_case` wins over the global default of the same name. The global
   `default_video_call` policy always exists and cannot be changed through the API.
4. Validation (error `policy_invalid`, 422, listing each problem): unknown settings are refused;
   `0 ≤ reject_below_milli ≤ accept_min_milli ≤ 1000`; `drop_consecutive ≥ 1`;
   `re_evaluation_interval_ms ≥ 100`; penalties 0 to 1000; at most 16 model penalties; text values are ASCII.
5. Every policy creation is audit-logged (document 06).
6. There is **no setting that switches consent off** (document 04) and none that hides a `reject`.

| Method | Path | Status |
|---|---|---|
| POST | `/v1/policies` | Planned (P0-11) |
| GET | `/v1/policies` | Planned (P0-11) |
| GET | `/v1/policies/{policy_id}` | Planned (P0-11) |

## 5. Who may see participants' status (Proposed, decision D-17)

The PRD (FR-C.4) says each participant's trust score and explanation reaches the other participants and/or the
platform's own systems, "per the platform's configuration". The suite never says how a participant's app
receives it. Proposal:

1. The partner's own servers **always** get the full picture from `GET .../status` with their API key.
2. For participants' apps, a new SDK-only endpoint `GET /internal/v1/sessions/continuous/{session_id}/peers`
   returns the **other** participants only (never your own), at the level set by `participant_visibility`:
   - `none`: refused with `403 peers_not_permitted`
   - `outcome`: just `accept`, `fallback` or `reject`
   - `outcome_and_reasons` (proposed default): outcome plus the plain-language reason codes, so the indicator
     can explain itself and is never a bare score (Design System section 6.1)
   - `full`: also the confidence number
3. **Symmetric:** the same level applies to everyone on the call (PRD FR-C.4's symmetric intent).

| Method | Path | Status |
|---|---|---|
| GET | `/internal/v1/sessions/continuous/{session_id}/peers` | Proposed |

## 6. What the engine never does

- Never receives or stores raw video or audio.
- Never changes the reported confidence.
- Never decides anything about identity, only about whether a stream looks live and unaltered.
- Never gives different answers to the same inputs, so partners can test it in their own pipelines.

## 7. Decisions for you to confirm

1. `fallback_behavior` defaults to `indicator_only` (a borderline result is visible but sends no webhook).
2. Participants can see others' status at the `outcome_and_reasons` level by default, through a new `peers` endpoint.
3. A `session.confidence_recovered` event is added so partners can clear a flag.
4. Penalties by trust tier and by model version subtract from the confidence, rather than changing thresholds.
