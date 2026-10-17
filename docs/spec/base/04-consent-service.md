# 04. Consent service

## In plain words

Nobody's camera may be analysed unless that person has clearly agreed. This document says how Certivo records
that agreement, how it is **enforced by the server and not merely by a screen**, and how a person can take
it back. Two different agreements exist and are never mixed: agreeing to be checked during calls, and agreeing
to a lasting trusted-device credential (Privacy Architecture, section 2.3; PRD FR-5.1 and FR-5.6). A partner
cannot switch consent off. That is a Vision non-negotiable ("no integration may bypass consent").

## 1. The two kinds of consent

| Type | What the person agrees to | Needed for | Status |
|---|---|---|---|
| `base_verification` | Their camera and microphone being analysed **on their own device** for the whole call, and a score and reason codes being sent to Certivo and the platform. No raw video or audio leaves the device. | Any score packet being accepted | Planned (P0-51) |
| `trusted_device` | A lasting, revocable credential being created for this device on this platform only | Issuing a Trusted Device Token | Planned (P1-05) |

One never satisfies the other. Granting `base_verification` does not grant `trusted_device`, and the reverse.

## 2. What is stored

One **append-only** row per decision. Nothing is edited or deleted in place.

| Field | Meaning |
|---|---|
| `id` | `con_` plus 32 hex |
| `partner_id` | The platform the consent was given on |
| `participant_reference` | The platform's own opaque ID for the person. We store no name, email or phone number |
| `consent_type` | `base_verification` or `trusted_device` |
| `decision` | `granted`, `declined` or `withdrawn` |
| `language_version` | Which wording the person saw, for example `base-2026-10-v1`. Certivo owns the wording and its versions |
| `locale` | Language of the wording shown, for example `en-GB` |
| `session_id` | The call it was given during, if any |
| `device_id` | The device that recorded it |
| `source` | `sdk` (the person, on their device) or `partner` (a withdrawal on the person's behalf) |
| `decided_at_ms` | When the person decided |
| `signature` | The device's signature over the decision (section 3), empty for `partner` withdrawals |

**Current state** for a person and type is the most recent row. Consent is valid until it is withdrawn, or
until Certivo publishes a new `language_version` marked as needing fresh consent.

## 3. Consent cannot be faked by a partner

The SDK records consent by signing it with the **device key**, using the same rules as score packets:

- Signed message = `certivo.consent.v1` + a newline + canonical JSON of:
  `v`, `session_id`, `participant_reference`, `device_id`, `consent_type`, `decision`, `language_version`,
  `locale`, `decided_at_ms`.
- The partner's server never holds a device key, so it cannot manufacture a "granted" record.
- A shared test vector for consent signatures is added with the build step (P0-51), the same way as for packets.

## 4. How it is enforced

1. The partner starts a session and passes the SDK token to the client.
2. The SDK checks whether current `base_verification` consent exists. If not, it shows the consent notice
   **before any camera access** (PRD FR-5.1; Design System `ConsentNotice`).
3. The person decides. The SDK sends the signed decision to the consent endpoint.
4. **Only after `granted` comes back does the SDK start capturing.**
5. **The server enforces the same rule.** A score packet from a participant with no current `granted`
   `base_verification` consent for that platform is refused with `409 consent_required`. Nothing is stored and
   no score is produced. There is no partner setting that turns this check off.
6. If the person **declines**, the call can continue without verification; the platform's own policy decides
   what that means for the call. Certivo shows "not verified", never "failed".

| Method | Path | Credential | Status |
|---|---|---|---|
| POST | `/internal/v1/sessions/continuous/{session_id}/consents` | SDK token and device signature | Planned (P0-51) |
| GET | `/v1/consents` | API key, scope `consents:read` | Planned (P0-51) |
| POST | `/v1/consents/withdrawals` | API key, scope `consents:write` | Planned (P0-51) |

## 5. Withdrawing consent

- **By the person**, in the app: the SDK records a signed `withdrawn` decision.
- **By the platform on the person's behalf** (a privacy request): `POST /v1/consents/withdrawals` with the
  participant's reference and the consent type. It is recorded with `source: partner`.
- **Effect is immediate.** The next packet is refused with `consent_required`; the SDK stops capturing at once;
  a `consent.withdrawn` webhook is sent (document 05); an audit entry is written (document 06).
- Withdrawing does not rewrite history: earlier sessions' attestations stay as they were.

## 6. Reading consent history

`GET /v1/consents?participant_reference=...&consent_type=...` returns the decision history for that person
on that platform, newest first, using the paging rules in document 01. A platform can only ever read its own
records.

## 7. Not decided here (deferred on purpose)

| Topic | Why deferred | Where it lands |
|---|---|---|
| How long consent records are kept | They are accountability evidence, so the period is a legal and privacy-review decision, not an engineering guess | P0-52 and P1-18 |
| Erasure requests | Deleting consent evidence may conflict with the duty to prove consent; the answer (delete versus one-way pseudonymise) needs counsel | P1-18 |
| Whether withdrawing `base_verification` also revokes Trusted Device Tokens | Depends on how the Trusted Device Layer behaves; to be decided with its consent flow | P1-05 |
| Consent wording text and translations | Written with the UX work and reviewed by counsel | P0-51, P0-73 |

## 8. Decisions for you to confirm

1. Consent is **enforced by the server** (refuse packets without it), not only by the screen.
2. Consent is **signed by the device key** so a partner cannot fabricate it.
3. Base consent is given **once per person per platform** and lasts until withdrawn, not asked again on every call
   (matching the in-call flow in the UX Specification, section 2.1).
