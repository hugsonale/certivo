# 05. Webhooks

## In plain words

A webhook is Certivo calling a partner's server to say "something just happened", for example "a participant's
confidence dropped". Because a partner's server must be sure the message really came from Certivo, every
message is signed. Because networks fail, Certivo retries, which means the same message can arrive twice, so
partners must be able to ignore duplicates.

**How it works:** when something happens, the event is written to the database in the **same transaction** as the
change that caused it, so an event is never lost and never sent for a change that was rolled back. A background
worker (Celery with Redis) turns each event into one delivery per subscribed endpoint, signs it and sends it.
The database, not Redis, is the source of truth for what is waiting and when it is next due: losing Redis only
delays deliveries, it never loses them. Events that happened before an endpoint existed are not sent to it.

## 1. Webhook endpoints (what a partner sets up)

| Method | Path | Purpose | Status |
|---|---|---|---|
| POST | `/v1/webhook-endpoints` | Register a URL and choose event types (or `*` for all). Returns the signing secret **once** | Implemented |
| GET | `/v1/webhook-endpoints` | List endpoints (never shows secrets) | Implemented |
| DELETE | `/v1/webhook-endpoints/{endpoint_id}` | Remove an endpoint | Implemented |
| POST | `/v1/webhook-endpoints/{endpoint_id}/rotate-secret` | New secret; the old one also signs for an overlap window | Implemented |
| POST | `/v1/webhook-endpoints/{endpoint_id}/test` | Send a `webhook.test` event | Implemented |
| GET | `/v1/webhook-deliveries` | Delivery log: what was sent, when, with what result | Implemented |
| POST | `/v1/webhook-deliveries/{delivery_id}/retry` | Send a failed or dead delivery again | Implemented |

**URL rules** (error `webhook_url_invalid`, 422):

- `https` only. Plain `http` is allowed only when the platform runs in dev (`CERTIVO_ENV=dev`).
- No username or password inside the URL; no redirects are followed.
- The address must be **public**. At delivery time the name is resolved and the call is refused if it points at
  a private, loopback, link-local or cloud-metadata address. We then connect to the address we checked, not to the
  name again, so a name cannot answer "public" for the check and "internal" for the connection. This stops a
  partner (or an attacker with a partner's key) using our servers to probe internal networks. For testing
  against your own PC, dev only: `CERTIVO_WEBHOOK_ALLOW_PRIVATE_TARGETS=true` (the app refuses to start with
  it outside dev). Obvious private names (`localhost`, `*.internal`, `*.local`, single-word hosts) and private
  IP addresses are also refused at registration; the full check happens at every delivery.

## 2. The message

Every delivery is an HTTP POST with a JSON body:

```json
{
  "id": "evt_0123456789abcdef0123456789abcdef",
  "type": "session.confidence_dropped",
  "created_at_ms": 1760000004000,
  "api_version": "v1",
  "partner_id": "ptn_...",
  "data": { "session_id": "cs_...", "participant_reference": "bob", "outcome": "reject" }
}
```

Headers: `Certivo-Event-Id`, `Certivo-Event-Type`, `Certivo-Signature`, `Content-Type: application/json`.

**Data minimisation:** a payload contains IDs, small integers and outcome words only. Never raw media, never
free text, never a face, name or contact detail. `participant_reference` is the partner's own ID.

## 3. Proving a message came from Certivo

`Certivo-Signature` looks like `t=1760000004000,v1=<64 hex characters>`. To check it, the receiver:

1. Reads `t` (milliseconds) and `v1` from the header.
2. Refuses the message if `t` differs from its own clock by more than 300 seconds (**placeholder**), which
   stops replays of old captured messages.
3. Computes `HMAC-SHA256` using the endpoint's signing secret over the text `t` + `.` + the **exact raw body
   bytes**, as lowercase hex.
4. Compares that with `v1` using a **constant-time** comparison. Accept only if equal.

While a secret is being rotated the header carries two values (`v1=...,v1=...`); accept the message if
**either** matches. A worked example with fixed values is in
`docs/spec/test-vectors/webhook-signature-v1.json`; every implementation must reproduce it.

**Secret storage:** the signing secret (`whsec_` plus 43 characters) is stored **encrypted** at rest (we must
be able to sign with it, so it cannot be a one-way hash), under a key from the secrets manager (P0-63). It is
shown to the partner once.

## 4. Delivery guarantees and what the receiver must do

- **At least once.** A message may arrive more than once. **De-duplicate by `id`, and remember an ID only AFTER
  you have handled the message successfully.** If you record the ID first and your handler then fails, our retry
  of that same event looks like a duplicate and the event is lost. Keep IDs for longer than the retry period.
  A reference implementation (`verify_signature` and `ReplayGuard`) is in `platform/app/webhook_verify.py`, with
  only the Python standard library, so a partner can copy it.
- **No ordering promise.** Use `created_at_ms` and the data to decide what is newest.
- **Reply with any 2xx within the time limit** (placeholder: 10 seconds). Do slow work after replying.
- Anything else, including a timeout, counts as a failure and is retried.

**Retry schedule (placeholder, to be tuned on real delivery data):** immediately, then after 30 seconds,
5 minutes, 30 minutes, 2 hours, 6 hours and 12 hours, which is seven attempts over about 21 hours. It is the
setting `CERTIVO_WEBHOOK_RETRY_DELAYS_S` (`30,300,1800,7200,21600,43200`). After the last failure the delivery
is marked `dead`. Every attempt is signed afresh with the time of that attempt, so the replay window always
applies. A redirect is a failure, and is never followed.
A partner can retry a dead delivery by hand. If every delivery to an endpoint keeps ending `dead` for several
days, the endpoint is marked `disabled` (Proposed) and the change is audit-logged.

| Delivery state | Meaning |
|---|---|
| `pending` | Waiting for its first attempt |
| `delivered` | The partner answered 2xx |
| `retrying` | A failed attempt; another is scheduled |
| `dead` | Every attempt failed; needs a manual retry |

The `webhook_deliveries` table records each delivery's state, attempt count, next attempt time, last HTTP status
and a short error code (`timeout`, `connection_error`, `tls_error`, `blocked_address`, `dns_error`, `redirect`,
`http_status`, `invalid_url`, `request_error`, `endpoint_deleted`). The `webhook_attempts` table is the log of
every try. **Neither ever stores the partner's response body**, which could contain anything.

A delivery being sent is locked for a short time (`webhook_lease_s`) with a one-time claim token. If a worker
dies, the lock runs out and another worker takes over; a slow worker that comes back late finds its token
replaced and does nothing. Deleting an endpoint marks everything still waiting for it `dead` with the error
`endpoint_deleted`.

## 5. Event catalogue

| Event | Sent when | Data fields | Status |
|---|---|---|---|
| `session.confidence_dropped` | A participant enters `reject` (always), or `fallback` when the policy sets `flag_for_review` | `session_id`, `participant_reference`, `seq`, `confidence_milli`, `occurred_at_ms`; `outcome` is added in P0-11 | Implemented |
| `session.paused` | Verification became unavailable for a session | `session_id`, `reason`, `occurred_at_ms` | Implemented |
| `session.resumed` | Verification came back after a pause | `session_id`, `occurred_at_ms` | Proposed |
| `session.confidence_recovered` | A participant returned to `accept` after `reject` | `session_id`, `participant_reference`, `seq`, `occurred_at_ms` | Proposed |
| `consent.withdrawn` | Consent was withdrawn by the person or on their behalf | `participant_reference`, `consent_type`, `occurred_at_ms` | Planned (P0-51) |
| `device_switch.detected` | An account tried a session from a device other than its trusted one | `participant_reference`, `session_id`, `occurred_at_ms` | Planned (P1-06) |
| `trusted_device.revoked` | A Trusted Device Token was revoked | `device_id`, `reason`, `occurred_at_ms` | Planned (P1-02) |
| `webhook.test` | A partner pressed "send test" (sent only to that endpoint, whatever it subscribed to) | none (empty `data`) | Implemented |

`session.confidence_dropped`, `session.paused`, `device_switch.detected` and `trusted_device.revoked` come from
the API Specification's event list (Doc 6, section 12). The rest are additions and are marked as such.

## 6. Decisions for you to confirm

1. Retry timings and the 5-minute replay window are placeholders; you only need to agree with the approach.
2. The two new events, `session.resumed` and `session.confidence_recovered`, are added so a partner can clear
   a warning it showed.
3. Endpoints that keep failing are disabled after several days (Proposed), not retried forever.
