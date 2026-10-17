# 02. Authentication and keys

## In plain words

Different callers prove who they are in different ways, and each proof opens only the doors that caller needs.
A partner's server uses an **API key**. The Certivo code running inside a partner's app uses a short-lived
**session token** plus a **device key** that signs what it sends. Certivo signs its own results with a
**platform key** that anyone can check. This document lists every credential, what it can do, and the
rules for creating, rotating and revoking each one.

## 1. Credentials at a glance

| Credential | Held by | Looks like | Used for | Status |
|---|---|---|---|---|
| Partner API key | The partner's server | `cvk_` + 43 characters | Everything under `/v1/` | Implemented |
| SDK session token | The SDK for one call | `skt_` + 43 characters | SDK endpoints for exactly one session | Implemented |
| Device signing key | One SDK installation on one device | Ed25519 key pair; only the public half reaches us | Signing score packets and consent records | Implemented (packets); Planned (consent, P0-51) |
| Webhook signing secret | The partner's server | `whsec_` + 43 characters | Checking that a webhook really came from Certivo (document 05) | Implemented |
| Platform signing key | Certivo | Ed25519 key pair; public half published | Signing session attestations | Implemented (basic); Planned (rotation, P0-10) |
| Dashboard login | A human at a partner | Email plus single sign-on and a second factor | The partner dashboard only | Planned (P1-11), not part of this plane |

## 2. Partner API keys

1. **Format:** `cvk_` followed by 43 URL-safe random characters (256 bits).
2. **Storage:** only the SHA-256 hash is stored, plus the first 12 characters for display. A plain hash is
   safe here because the key is long and random; this is not a password. A key is shown **once**, at creation.
3. **Revocation is immediate.** Every request checks the database; there is no cache that could keep a revoked
   key working. A revoked key gets the same `invalid_api_key` as a made-up one.
4. **Scopes.** A key carries a list of scopes and may only call endpoints that need those scopes. A missing
   scope returns `403 forbidden_scope` and names the scope. Keys that existed before this was built were
   given every scope by a migration, so nothing that worked stopped working. **A key can never grant
   scopes it does not hold itself**, and creating, listing or revoking keys needs `keys:admin`.
5. **Several keys per partner**, so keys can be rotated without downtime, up to a cap on active keys
   (`max_api_keys_per_partner`, default 50, **placeholder**; error `api_key_limit_reached`). Each key has a
   name to tell them apart.
6. **Rotation** is: create the new key, deploy it, revoke the old one. Both work in between.
7. **Last use** (`last_used_at_ms`) is recorded at most once a minute per key, so partners can see which keys
   are idle. Revoked keys keep their row with `revoked_at_ms`, so history is not lost.
8. **If a key leaks:** revoke it, create a new one, check the audit log (document 06) for its use. Our secret
   scanner recognises the `cvk_` format.
9. **Creating the first key** for a new partner is a Certivo-staff action (`scripts/create_partner.py`). There
   is no public admin API in Phase 0.

| Scope | Allows |
|---|---|
| `sessions:write` | Start and end sessions |
| `sessions:read` | Read session status and attestations |
| `devices:write` | Register and revoke devices |
| `devices:read` | Read devices |
| `policies:write`, `policies:read` | Create and read policies |
| `webhooks:write`, `webhooks:read` | Manage webhook endpoints, read and retry deliveries |
| `consents:write`, `consents:read` | Record partner-initiated withdrawals, read consent history |
| `audit:read` | Read the audit log |
| `analytics:read` | Read aggregate analytics |
| `keys:admin` | Create, list and revoke API keys |

## 3. SDK session tokens

1. Returned **once** when a session starts, to the partner's server, which hands it to its own client.
2. Valid for **one session only**. It cannot read other sessions and cannot call `/v1/` endpoints.
3. Allowed actions: send score events, pause, resume, record consent, read peers' status (if the policy
   permits), send telemetry.
4. **Not allowed:** read the session's status, end it, register devices.
5. **Time limit:** expires `sdk_token_ttl_seconds` after the session starts (**placeholder: 6 hours**, to be set
   from real partner call lengths). The start response includes `sdk_token_expires_at_ms`. At and after that
   moment: `401 session_token_expired`.
6. **After the session ends** the SDK endpoints answer `409 session_not_active`; there is nothing left to do.
7. Only the SHA-256 hash is stored.

## 4. Device keys and trust tiers

1. Each SDK installation makes its own key pair locally. The private key never leaves the device.
2. In Phase 0 the **partner registers** the device's public key (`POST /v1/devices`), which means the partner
   vouches that it belongs to a genuine SDK install. Phase 1 adds hardware and platform attestation, which
   upgrades the tier without the partner's word (Trusted Device Layer, P1-03).
3. **Trust tiers** follow the Technical Requirements Document, Table 8.1: Tier 1 hardware-attested, Tier 2
   platform-authenticated, Tier 3 software-only. Phase 0 issues only `software_only`.
4. **Changed from the suite:** the suite defines Tier 3 as a device fingerprint plus behavioural signals from a
   "Device Trust Service". No such service exists, and fingerprinting is itself a privacy risk (Privacy
   Architecture, section 3). **Tier 3 here means only "a registered software-held key".** We build no
   fingerprinting now. Revisit with the privacy review (P0-52). See ADR 0007.
5. **Revoking a device** (`DELETE /v1/devices/{device_id}`) is immediate. From then on its packets get
   `invalid_device_signature`. Revoking twice is harmless. The device row stays, with `revoked_at_ms`.
6. A signature proves **which key said it**, not that the statement is true. See Build Spec 0, section 9.

## 5. The platform signing key and published keys

1. Certivo signs each attestation with the platform key. Anyone can verify it using the public key, without
   contacting Certivo's API (PRD FR-4.2).
2. **Rotation without breaking old attestations** (PRD FR-4.4): a new key is added; the old key stays
   published and is marked `retired`. Old attestations keep verifying forever.
3. **If a platform key is compromised:** it is marked `revoked` with a time. Verifiers must treat attestations
   signed by that key after the compromise time as untrustworthy.
4. **Published format** (Planned, P0-10): each entry has `key_id`, `alg`, `public_key`, `status` (`active`,
   `retired` or `revoked`), `not_before_ms`, and `retired_at_ms` when relevant. Today's endpoint returns
   `key_id`, `alg` and `public_key` for the one active key.
5. **Where the private key lives:** an environment value in development; a managed key service in production,
   never a file in the code or image (P0-10, P0-63). In production the service refuses to start without it.

## 6. Rules that apply to every credential

- All traffic uses TLS 1.2 or newer (PRD NFR-3.1), terminated at the edge (P1-17).
- Credentials never appear in logs, errors or audit metadata. Log lines redact the `Authorization` header
  (Planned, P0-13).
- Comparisons of secret values are constant-time.
- Failed authentication is rate limited by network address and by the first 12 characters of the credential
  presented: after too many failures from one address, even a correct key from that address is refused with
  `429 rate_limited` for a while, which is what slows a guessing attack. Successful traffic is limited per API
  key and per SDK session. All three limits are settings (**placeholders**) chosen from measured traffic.
- The network address is the direct connection's address. `X-Forwarded-For` is trusted only when the
  `trusted_proxy_hops` setting says how many reverse proxies sit in front of the service (default 0), so a
  caller cannot dodge a limit by inventing the header.
- A credential is only ever accepted in the `Authorization` header, never in a URL.

## 7. Access matrix

One row per endpoint. "Implemented" rows are checked against the running code by an automated test.

| Method | Path | Credential | Scope | Status |
|---|---|---|---|---|
| GET | `/healthz` | none | none | Implemented |
| GET | `/.well-known/certivo-keys` | none | none | Implemented |
| POST | `/v1/devices` | API key | `devices:write` | Implemented |
| GET | `/v1/devices/{device_id}` | API key | `devices:read` | Implemented |
| DELETE | `/v1/devices/{device_id}` | API key | `devices:write` | Implemented |
| POST | `/v1/sessions/continuous` | API key | `sessions:write` | Implemented |
| POST | `/v1/sessions/continuous/{session_id}/end` | API key | `sessions:write` | Implemented |
| GET | `/v1/sessions/continuous/{session_id}/status` | API key | `sessions:read` | Implemented |
| GET | `/v1/sessions/continuous/{session_id}/attestation` | API key | `sessions:read` | Planned (P0-10) |
| POST | `/internal/v1/sessions/continuous/{session_id}/score-events` | SDK token and device signature | none | Implemented |
| POST | `/internal/v1/sessions/continuous/{session_id}/score-events/batch` | SDK token and device signature | none | Implemented |
| POST | `/internal/v1/sessions/continuous/{session_id}/pause` | SDK token | none | Implemented |
| POST | `/internal/v1/sessions/continuous/{session_id}/resume` | SDK token | none | Implemented |
| POST | `/internal/v1/sessions/continuous/{session_id}/consents` | SDK token and device signature | none | Planned (P0-51) |
| GET | `/internal/v1/sessions/continuous/{session_id}/peers` | SDK token | none | Proposed |
| POST | `/internal/v1/sessions/continuous/{session_id}/telemetry` | SDK token | none | Planned (P0-27) |
| POST | `/v1/api-keys` | API key | `keys:admin` | Implemented |
| GET | `/v1/api-keys` | API key | `keys:admin` | Implemented |
| DELETE | `/v1/api-keys/{key_id}` | API key | `keys:admin` | Implemented |
| POST | `/v1/policies` | API key | `policies:write` | Planned (P0-11) |
| GET | `/v1/policies` | API key | `policies:read` | Planned (P0-11) |
| GET | `/v1/policies/{policy_id}` | API key | `policies:read` | Planned (P0-11) |
| POST | `/v1/webhook-endpoints` | API key | `webhooks:write` | Implemented |
| GET | `/v1/webhook-endpoints` | API key | `webhooks:read` | Implemented |
| DELETE | `/v1/webhook-endpoints/{endpoint_id}` | API key | `webhooks:write` | Implemented |
| POST | `/v1/webhook-endpoints/{endpoint_id}/rotate-secret` | API key | `webhooks:write` | Implemented |
| POST | `/v1/webhook-endpoints/{endpoint_id}/test` | API key | `webhooks:write` | Implemented |
| GET | `/v1/webhook-deliveries` | API key | `webhooks:read` | Implemented |
| POST | `/v1/webhook-deliveries/{delivery_id}/retry` | API key | `webhooks:write` | Implemented |
| GET | `/v1/consents` | API key | `consents:read` | Planned (P0-51) |
| POST | `/v1/consents/withdrawals` | API key | `consents:write` | Planned (P0-51) |
| GET | `/v1/audit-logs` | API key | `audit:read` | Planned (P0-13) |
| GET | `/v1/analytics/sessions` | API key | `analytics:read` | Planned (P1-11) |
| GET | `/v1/analytics/call-quality` | API key | `analytics:read` | Planned (P1-11) |

## 8. Key management in practice

- `POST /v1/api-keys` with `{"name": "...", "scopes": ["sessions:read"]}` returns the new key **once** in the
  `key` field. Store it immediately.
- `GET /v1/api-keys` lists keys (never the secret): `id`, `name`, `scopes`, `key_prefix`, `active`,
  `created_at_ms`, `last_used_at_ms`, `revoked_at_ms`.
- `DELETE /v1/api-keys/{key_id}` revokes at once and answers 204. **Nothing stops a partner revoking its own
  only `keys:admin` key.** If that happens, Certivo staff issue a new one. A guard against it can be added
  later if partners ask for one.
