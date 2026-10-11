# 01. API conventions and errors

## In plain words

Every Certivo endpoint follows the same habits: the same way of writing times and scores, the same shape of
error, and the same rules for what is safe to retry. A developer who learns one endpoint should be able to
predict the rest. This document also lists every error code in one place so partners can write code against
them and never have to parse our human-readable messages.

## 1. Conventions

| Topic | Rule | Status |
|---|---|---|
| Versioning | Public endpoints live under `/v1/`. Endpoints used only by the SDK live under `/internal/v1/`. Adding fields or endpoints is allowed within `v1`; removing or changing meaning needs `v2`. | Implemented |
| Format | Requests and responses are JSON, UTF-8. | Implemented |
| Times | Whole milliseconds since 1 January 1970 UTC, in fields ending `_ms`. | Implemented |
| Scores | Whole numbers from 0 to 1000 in fields ending `_milli`. No decimals anywhere that is signed. | Implemented |
| IDs | A short prefix, an underscore, and 32 hex characters: `ptn_` partner, `key_` API key, `pol_` policy, `dev_` device, `cs_` continuous session. Planned prefixes: `whe_` webhook endpoint, `evt_` event, `con_` consent, `aud_` audit entry. IDs are opaque; never parse them. | Implemented |
| Request ID | Every response carries `X-Request-ID` (`req_` plus 16 hex). Errors repeat it in the body. Quote it when asking for support. | Implemented |
| Authentication | `Authorization: Bearer <credential>`. See document 02. | Implemented |
| Other people's resources | Asking for something that belongs to another partner returns 404, never 403, so existence is not revealed. | Implemented |
| Request size | JSON bodies larger than the limit are refused with `413 payload_too_large`. The limit is a setting (placeholder: 64 KiB). | Planned (P0-06) |
| Rate limits | Too many requests get `429 rate_limited` with a `Retry-After` header and `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` headers. Limits are settings chosen from measured load, not guessed here. | Planned (P0-06) |
| Idempotency | Callers may send `Idempotency-Key` (up to 64 printable ASCII characters) on `POST /v1/sessions/continuous` and `POST /v1/devices`. The same key with the same body within 24 hours returns the original response; the same key with a different body returns `422 idempotency_key_reuse`. Score events are already idempotent by `seq` (Build Spec 0, section 4). | Proposed |
| Lists | Cursor paging: `?limit=` (1 to 100, default 25) and `?cursor=`. Response: `{"data": [...], "next_cursor": "..." or omitted}`. | Planned (P0-13) |
| SDK version | The SDK sends `Certivo-SDK-Version: <semver>` and `Certivo-SDK-Platform: web\|ios\|android` on every request. The server accepts several SDK versions at once. | Planned (P1-14) |

## 2. The error envelope

Every error, including unexpected crashes, has this shape and nothing else:

```json
{
  "error": {
    "code": "seq_conflict",
    "message": "A different packet already used this seq",
    "request_id": "req_0123456789abcdef",
    "details": [ { "loc": ["body", "seq"], "msg": "...", "type": "..." } ]
  }
}
```

Rules:

1. **`code` is the contract.** It is stable, lowercase, with underscores, and is never renamed or reused for a
   different meaning. Partners write code against it.
2. **`message` is for humans** and may be reworded at any time. Never parse it.
3. **`details`** appears only for `validation_error`, listing which field failed and why.
4. **No secrets and no personal data** in any error. Not the key that failed, not the submitted value, not a
   stack trace.
5. **5xx errors are generic.** Details go to our logs, found by `request_id`.
6. **Unknown or revoked credentials look the same** (`invalid_api_key`), so an attacker cannot tell which.

## 3. Error code catalogue

"Retry?" says whether sending the identical request again can ever succeed without changing something.

| Code | HTTP | Status | Meaning | Retry? |
|---|---|---|---|---|
| `missing_api_key` | 401 | Implemented | No `Authorization: Bearer` header on a partner endpoint | No |
| `invalid_api_key` | 401 | Implemented | Key unknown, revoked or malformed | No |
| `missing_session_token` | 401 | Implemented | No session token on an SDK endpoint | No |
| `invalid_session_token` | 401 | Implemented | Token does not match this session | No |
| `invalid_device_signature` | 401 | Implemented | Device unknown, revoked, not this partner's, or the signature does not verify | No |
| `session_not_found` | 404 | Implemented | No such session for this credential | No |
| `policy_not_found` | 404 | Implemented | No policy configured for the requested use case | No |
| `device_not_found` | 404 | Implemented | No such device for this partner | No |
| `session_not_active` | 409 | Implemented | The session has already ended | No |
| `seq_conflict` | 409 | Implemented | A different packet already used this `seq` | No |
| `seq_out_of_order` | 409 | Implemented | `seq` is lower than one already accepted for that participant | No |
| `non_monotonic_interval` | 409 | Implemented | `interval_end_ms` went backwards for that participant | No |
| `validation_error` | 422 | Implemented | A field is missing, the wrong type or out of range (see `details`) | No |
| `non_canonical_payload` | 422 | Implemented | A signed value breaks the canonical JSON rules (Build Spec 0, section 4) | No |
| `invalid_interval` | 422 | Implemented | Interval is empty or longer than the maximum | No |
| `timestamp_in_future` | 422 | Implemented | `interval_end_ms` is too far ahead of server time | After the clock catches up |
| `invalid_public_key` | 422 | Implemented | Not a 32-byte Ed25519 key | No |
| `http_<status>` | as given | Implemented | Framework-level errors with no Certivo code, for example `http_404` for an unknown URL and `http_405` for a wrong method | Depends |
| `internal_error` | 500 | Implemented | Something unexpected broke on our side | Yes, with backoff |
| `forbidden_scope` | 403 | Planned (P0-06) | The key is valid but lacks the scope this endpoint needs | No |
| `session_token_expired` | 401 | Planned (P0-06) | The SDK token's time limit has passed | No |
| `rate_limited` | 429 | Planned (P0-06) | Too many requests; obey `Retry-After` | Yes, after the delay |
| `payload_too_large` | 413 | Planned (P0-06) | Body exceeds the size limit | No |
| `service_unavailable` | 503 | Planned (P0-13) | Temporarily cannot serve (for example database down) | Yes, with backoff |
| `policy_invalid` | 422 | Planned (P0-11) | A submitted policy breaks the rules in document 03 | No |
| `consent_required` | 409 | Planned (P0-51) | No current granted consent for this participant (document 04) | After consent is recorded |
| `peers_not_permitted` | 403 | Planned (P1-10) | The session's policy does not let participants see each other's status | No |
| `webhook_url_invalid` | 422 | Planned (P0-07) | Webhook URL is not allowed (document 05) | No |
| `idempotency_key_reuse` | 422 | Proposed | Same `Idempotency-Key` with a different body | No |

## 4. How partners should handle errors

- **Switch on `code`, log `request_id`.**
- **4xx** (other than 408, 429): the request is wrong; fix it, do not retry unchanged.
- **429, 500, 503:** retry with exponential backoff and jitter. Respect `Retry-After`.
- **During a live call, never end the call because of an error.** A failed packet upload is buffered and
  retried by the SDK (System Design Document, section 7.1). A partner's own integration should treat any
  error from Certivo as "verification paused", never as "verified" and never as "failed".
