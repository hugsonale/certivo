# Certivo Build Spec 0

**Status:** draft for Jesutofunmi's review. **Scope:** Phase 0, the continuous-session backbone.
**Code that implements it:** `platform/` (197 tests, on SQLite and on Postgres).
**Derived from:** the v2 suite (chiefly Doc 6 API Specification §10, plus Docs 2, 4, 5, 12).
Where this spec departs from a document it says so in section 3. The suite's "Version 1.0"
documents were never written, so the base parts they were meant to supply (error codes,
authentication, policy engine, consent, webhooks, audit and analytics) are defined in
`docs/spec/base/` and settled item by item in `docs/spec/RECONCILIATION.md` (step P0-05).

---

## 1. What Phase 0 is (and is not)

Phase 0 proves the plumbing end to end with **no ML**:

> device signs a score packet → backend authenticates it → policy outcome per participant →
> partner reads live status → session ends → platform signs an attestation that discloses gaps.

It is done when a scripted two-person call (`scripts/sandbox_call.py`) shows one participant
dropping to `reject` mid-call, and the signed attestation verifies and tells the truth.

**Not in Phase 0:** any real model, the Web SDK, WebRTC, native attestation (App Attest / Play
Integrity), the Trusted Device Layer (Doc 6 §11), webhook *delivery*, retention jobs, rate
limiting, mobile.

## 2. Phase 0 endpoint catalogue

Auth: **partner** endpoints use `Authorization: Bearer cvk_…` (partner API key).
**SDK** endpoints use `Authorization: Bearer skt_…` (per-session token returned by session start).
Keys carry scopes, tokens expire, and requests are rate limited and size limited: see
`docs/spec/base/01` and `02`. The access matrix in `base/02` is the authoritative list of endpoints.

| Method + path | Auth | Purpose |
|---|---|---|
| `POST /v1/devices` | partner | Register a device signing key (`public_key`, Ed25519, base64url). Tier is always `software_only` in Phase 0. |
| `GET /v1/devices/{id}` | partner | Read a device. |
| `POST /v1/sessions/continuous` | partner | Start. Body: `use_case`, optional `call_session_reference`, `participant_count` (positive int, default 1). Returns `id`, `status`, `re_evaluation_interval_ms`, `sdk_token` (shown once) and `sdk_token_expires_at_ms`. |
| `POST /internal/v1/sessions/continuous/{id}/score-events` | SDK | Submit one signed packet (section 4). Returns `accepted`, `seq`, `current_policy_outcome`, `duplicate`. |
| `POST /internal/v1/sessions/continuous/{id}/score-events/batch` | SDK | Upload packets the SDK buffered during an outage (P0-08). Body `{packets: [1 to 25 packets, oldest first]}`. Each packet is checked on its own; returns `results[]` (`index`, `accepted`, `seq`, `current_policy_outcome`, `duplicate`, or `error {code, message}`) and counts. Re-sending a batch is safe. Late or missing packets are disclosed as coverage gaps (section 8). |
| `POST /internal/v1/sessions/continuous/{id}/pause` | SDK | Declare verification unavailable. Body `{reason}`: `connectivity` \| `sdk_error` \| `model_unavailable` \| `other`. Opens a coverage gap. 204. |
| `POST /internal/v1/sessions/continuous/{id}/resume` | SDK | Close the gap. 204. |
| `POST /v1/sessions/continuous/{id}/end` | partner | End. Returns the signed attestation and `coverage_summary`. Idempotent. |
| `GET /v1/sessions/continuous/{id}/status` | partner | Latest confidence, outcome and explanation per participant, plus `session_status`. |
| `GET /.well-known/certivo-keys` | none | Public attestation verification keys. |
| `GET /healthz` | none | Liveness. |

Errors use one envelope: `{"error": {"code", "message", "request_id", "details?"}}`. Codes in use:
`missing_api_key`, `invalid_api_key`, `missing_session_token`, `invalid_session_token`,
`invalid_device_signature` (401); `session_not_found`, `policy_not_found`, `device_not_found`
(404); `session_not_active`, `seq_conflict`, `seq_out_of_order`, `non_monotonic_interval` (409);
`validation_error`, `non_canonical_payload`, `invalid_interval`, `timestamp_in_future`,
`invalid_public_key` (422). The full catalogue, including planned codes, is
`docs/spec/base/01-api-conventions-and-errors.md`.

## 3. Deviations from Doc 6 §10 (deliberate, please confirm)

| Doc 6 says | Spec 0 does | Why |
|---|---|---|
| `confidence`: number 0.0 to 1.0 | `confidence_milli`: integer 0 to 1000 | Floats serialise differently across JS/Swift/Kotlin/Python; signing needs byte-identical output. |
| Packet = participant_reference, confidence, explanation, device_signature | Adds `v`, `device_id`, `seq`, `interval_start_ms`, `interval_end_ms`, `model_version` | Replay protection, ordering, gap accounting, and auditability of which model produced a score. `session_id` is bound into the signature. |
| `explanation`: "structured object" | `{reason_codes: [≥1 code], signal_milli: {name: 0..1000}}` | Enforces "never a bare score". Free text is not allowed (it breaks canonicalisation and can leak data). |
| `device_signature`: "signature over this packet" | Defined in section 4 | Doc leaves the algorithm and byte format open. |
| 409 when `reported_at` is inconsistent | `session_not_active`, `seq_out_of_order`, `non_monotonic_interval` | `interval_end_ms` plays the role of `reported_at`. |
| SDK auth not defined in the suite (defined in `base/02`) | Partner API key for `/v1`, per-session token for `/internal` | SDK code ships to end users and must never hold the partner secret. |
| (none) | New: `POST /v1/devices`, `GET /v1/devices/{id}`, `/pause`, `/resume`, `/.well-known/certivo-keys` | Doc 6 refers to a "provisioned signing key" but defines no provisioning endpoint; pause/resume feed `coverage_summary`. |

Doc 6 §11 (Trusted Devices) and §12 webhook catalogue are **not** implemented beyond recording
`session.confidence_dropped` and `session.paused` in an outbox table.

## 4. Score packet and signing (the cross-language contract)

**Packet (what the SDK sends)**

```json
{
  "v": 1,
  "participant_reference": "alice",
  "device_id": "dev_<32 hex>",
  "seq": 3,
  "interval_start_ms": 1760000003000,
  "interval_end_ms": 1760000004000,
  "confidence_milli": 912,
  "model_version": "edge-0.1.0",
  "explanation": {"reason_codes": ["consistent_motion"], "signal_milli": {"temporal": 940}},
  "device_signature": "<86-char base64url>"
}
```

**Signed message** = `domain || canonical_json(packet without device_signature, plus session_id)`

* `domain` = the ASCII bytes `certivo.score.v1\n` (prevents cross-protocol signature reuse).
* `session_id` comes from the URL path; including it makes a packet un-replayable in another session.
* **Algorithm:** Ed25519 (RFC 8032). Signature and public key are base64url with no padding
  (signature = 86 chars, public key = 43 chars).

**Canonical JSON profile** (small enough to reimplement by hand in any language):

1. UTF-8, no whitespace, object keys sorted ascending (byte order).
2. Keys match `^[a-z0-9_]{1,64}$` (so every language sorts identically).
3. Values are: integers with |n| ≤ 2^53−1, printable-ASCII strings (0x20–0x7E), arrays, objects.
4. **No** floats, booleans, nulls, or non-ASCII.

`docs/spec/test-vectors/score-packet-v1.json` holds a fixed key, packet, canonical bytes (hex)
and signature. Every SDK implementation must reproduce `canonical_bytes_hex` and
`signature_b64u` exactly before it is allowed to send traffic. A backend test fails if the file
and the code drift.

**Replay and ordering rules (per session + participant)**

* `seq` starts at 0 and must increase. Skipped values are allowed and counted as
  `missed_intervals`.
* Same `seq` + same signature → idempotent success (`duplicate: true`). Same `seq` with a
  different signature → `409 seq_conflict`.
* `interval_end_ms` must not go backwards (`409`), must be > start and ≤ 60 s long, and may not
  be more than 30 s ahead of server time (`422`).
* Packets for an ended session → `409 session_not_active`.
* A valid packet that arrives while the session is `paused` implicitly resumes it.

## 5. Session state machine

```
            start                     pause (SDK)
(none) ───────────► active ◄────────────────────────► paused
                      │   resume (SDK) or valid packet   │
                      └────────────── end (partner) ─────┘
                                       ▼
                                     ended   (terminal; end is idempotent)
```

The policy used for a session is **snapshotted at start**, so editing a policy mid-call never
changes a call in progress.

## 6. Policy rule (placeholder numbers, not validated)

Per participant, for each new interval with confidence `c` (milli):

* `c ≥ accept_min_milli (700)` → `accept`
* `reject_below_milli (400) ≤ c < 700` → `fallback`
* `c < 400` → `fallback` for the first low interval, `reject` once `drop_consecutive (2)` low
  intervals in a row have occurred. A later interval ≥ 400 leaves `reject` immediately.

`session.confidence_dropped` is recorded once on each transition into `reject`. **These
thresholds are scaffolding.** Real values come from the edge benchmark (Doc 7), not from us
guessing now.

## 7. Data model

Tables: `partners`, `api_keys` (SHA-256 hash only), `policies` (partner NULL = global default
`default_video_call`), `devices`, `continuous_sessions`, `continuous_score_events` (unique on
session+participant+seq), `coverage_gaps`, `webhook_outbox`, `session_attestations`.

The schema is defined **only** by Alembic migrations in `platform/migrations/` (baseline `0001`).
No code creates tables directly. Constraints and indexes have fixed names (a naming convention),
so later migrations can change them safely. Rules:

* `CERTIVO_ENV=dev`: the app applies migrations automatically at startup.
* Any other environment: the app never changes the database. Migrations are run explicitly
  (`alembic upgrade head`) and the app refuses to start if the database is not at the latest revision.
* CI runs the whole test suite on SQLite **and** on Postgres 16, and runs `alembic check`, which
  fails if `app/models.py` and the migrations disagree.
* On Postgres, JSON columns are `JSONB`; elsewhere plain JSON. Global policies (no partner) are
  protected by a partial unique index, because a plain UNIQUE constraint does not treat NULLs as equal.

Doc 12's daily partitioning of the score-events table is still a later migration.

Privacy posture carried over from the docs: no raw video or audio ever reaches this service;
explanations are code lists and 0..1000 numbers only. Per-interval events are intended to have
shorter retention than the attestation (Doc 11/10 direction); the retention job is not built yet.

## 8. The attestation

Returned by `end` and stored. Shape: `{payload, signature, key_id, alg: "Ed25519"}`.

`payload` (all ints and ASCII strings): `v`, `type` (`certivo_session_attestation`),
`session_id`, `partner_id`, `use_case`, optional `call_session_reference`, `started_at_ms`,
`ended_at_ms`, `issued_at_ms`, `key_id`, `policy {policy_id, version, config_sha256}`,
`participants[] {participant_reference, events_accepted, missed_intervals,
min_confidence_milli, mean_confidence_milli, final_outcome, reject_transitions}`,
`coverage {session_duration_ms, paused_ms, gap_count, coverage_milli, participants_declared,
participants_observed, gaps[], gaps_truncated}`.

**Verification (what a partner does):** fetch `/.well-known/certivo-keys`, pick the key with
`key_id`, then check Ed25519 over `b"certivo.attestation.v1\n" + canonical_json(payload)`.
Gaps are always disclosed in `coverage`; a session with no gaps says so explicitly
(`gap_count: 0`), it is never omitted.

`missed_intervals` = `last_seq + 1 − events_accepted` (assumes SDKs start at seq 0).

**Gap reasons and what `paused_ms` means.** `paused_ms` is the time in the session with no live verification. A gap's `reason` is one of: `connectivity`, `sdk_error`, `model_unavailable`, `other` (the SDK paused), `delayed_upload` (scores arrived, but long after the moment they describe, so the partner had no live signal meanwhile) or `missing_packets` (scores for that time never arrived). Overlapping gaps are counted once. The cut-off for "long after" is `CERTIVO_GAP_DISCLOSURE_THRESHOLD_MS` (placeholder, ADR 0014).

**Key handling:** the platform signing seed is read from `CERTIVO_ATTESTATION_SIGNING_KEY`. In
`prod` the service refuses to start without it; in dev it makes an ephemeral key and warns.
Rotation = new `key_id` + keep old public keys published (not built yet).

## 9. Security model and what Phase 0 does **not** prove

What it gives: packet integrity, origin-key authenticity, replay resistance, partner isolation,
hashed credentials, tamper-evident attestations.

What it does **not** give, and we must not claim:

* **Score honesty.** The device reports its own score. An attacker who controls the client
  can register their own key and sign "930" forever. A signature proves *which key said it*,
  not that it was true. This is the central weakness of sender-reported scoring; native
  attestation (Tier 1/2 devices) narrows it, and receiver-side scoring (below) is the real fix.
* **Hardware trust.** Every Phase 0 device is `software_only`.
* **Identity binding.** Nothing ties a face to a verified profile (Morgan Ellis persona).
* Rate limiting, request-size limits, TLS termination, secret-manager integration (all
  required before any external exposure).

## 10. Acceptance criteria (all currently met by `platform/tests`)

1. Valid packet accepted; tampered, wrong-session-bound, unknown-device packets rejected 401.
2. Duplicate is idempotent; conflicting `seq` is 409; out-of-order and backwards time are 409.
3. Two consecutive low intervals produce `reject` and exactly one `session.confidence_dropped`.
4. Pause/resume (explicit or implicit) produces a disclosed gap and a correct `coverage_milli`.
5. Attestation verifies with the published key and fails after any payload edit; `end` twice
   returns the identical attestation.
6. A partner cannot read or end another partner's session or device (404).
7. The shared test vector reproduces byte-for-byte.
8. `scripts/sandbox_call.py` against a live server prints a drop for `bob` and
   `attestation signature verified: True`.

## 11. Open decisions (need you)

1. **Ed25519 in browsers.** I believe current browsers support Ed25519 in WebCrypto, but
   verify before building the Web SDK. Fallback is ECDSA P-256 (add an `alg` field to
   `devices`). This is the first thing to check in the SDK spike.
2. **Receiver-side scoring.** Should a second signal exist where each participant's device
   scores the *incoming* stream? It changes the packet and the trust model; decide before the
   SDK hardens.
3. **Identity binding.** Is "same person as the verified profile" in or out of scope for the
   flagship? Out of scope means the dating-persona claim must be reworded.
4. ~~**v1 documents.**~~ Resolved in P0-05: they never existed. The base specifications are in
   `docs/spec/base/`. One new decision came out of it: **D-17**, how participants' apps receive each
   other's status (`base/03`, section 5).
5. **Who gets the SDK token?** Today the partner backend starts the session and hands the
   token to its client. Confirm that matches how design partners would integrate.

## 12. Next build tasks (in order)

1. Push, confirm CI is green on GitHub.
2. ~~Alembic migrations + Postgres in CI.~~ Done (P0-03, P0-04).
3. Web SDK spike: reproduce the test vector in the browser (settles open decision 1).
4. `demo-call/`: two-person WebRTC call using the sandbox flow, then the real SDK.
5. Webhook delivery worker (HMAC-signed, retries) reading `webhook_outbox`.
6. Rate limiting, body-size limits, retention job for score events.
7. Overhead measurement harness (CPU, memory, bandwidth) before any model work.
8. Edge model + evaluation harness (detection latency, false-trigger rate) before any
   accuracy claim.
9. Trusted Device Layer, web tiers first.
