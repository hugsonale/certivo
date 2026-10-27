# 08. Observability and the audit log

Reference for P0-13. Why these choices were made: `docs/adr/0019-observability-and-audit-log.md`.

## 1. Log line format

One JSON object per line on standard error.

| Field | Meaning |
| :---- | :---- |
| `ts` | UTC time, ISO 8601 with milliseconds, ending in `Z` |
| `level` | DEBUG, INFO, WARNING, ERROR |
| `logger` | `certivo.access`, `certivo.audit`, `certivo.errors`, ... |
| `msg` | What happened, in words |
| `request_id` | `req_` + 16 hex characters. Also returned to the caller in `X-Request-ID` |
| `trace_id`, `span_id` | Present only when tracing is switched on |
| other fields | Per message; see below |

**Access line** (`certivo.access`, message `request`): `method`, `route` (the template, such as
`/v1/policies/{policy_id}`), `path`, `status`, `duration_ms`, and when known `error_code`, `partner_id`,
`api_key_id`, `session_id`. INFO below 500, ERROR at 500 and above. Health checks and metric scrapes are not
logged unless they fail.

**Never in any log line:** API keys, SDK tokens, signatures, `Authorization` headers, cookies, request or
response bodies, query strings, network addresses, webhook URL paths, or anything about a person's face or voice.
Enforced by `app/logging_setup.py` and by tests in `tests/test_obs_logging.py`, `test_obs_middleware.py`, `test_obs_api.py`.

Settings: `CERTIVO_LOG_FORMAT` (`json` | `text`), `CERTIVO_LOG_LEVEL`.

## 2. Metrics (`GET /metrics`)

Needs `Authorization: Bearer <CERTIVO_METRICS_TOKEN>` (at least 16 characters). Without a token it is served
only when `CERTIVO_ENV=dev`.

| Metric | Type | Labels | Meaning |
| :---- | :---- | :---- | :---- |
| `certivo_http_requests_total` | counter | method, route, status | Requests handled |
| `certivo_http_request_duration_seconds` | histogram | method, route | Time to serve |
| `certivo_http_requests_in_progress` | gauge | | Requests being served now |
| `certivo_packets_total` | counter | via, result | Score packets: accepted, duplicate, rejected |
| `certivo_packets_rejected_total` | counter | via, code | Refused packets by API error code |
| `certivo_packet_ingest_lag_seconds` | histogram | via | Receive time minus end of the packet's interval |
| `certivo_auth_failures_total` | counter | reason | Failed credential checks |
| `certivo_rate_limited_total` | counter | scope | Requests refused with 429 |
| `certivo_attestation_sign_failures_total` | counter | | Times the signer was unreachable |
| `certivo_build_info` | gauge | version, env | Always 1 |

`via` is `live` or `batch`. Negative lag (a device clock slightly ahead) is recorded as zero.
Not yet exported: webhook delivery metrics (the worker is a separate process).

## 3. Audit log (`audit_events`)

| Action | When |
| :---- | :---- |
| `partner.created` | A partner is created |
| `api_key.created`, `api_key.revoked` | A key is issued or revoked |
| `policy.created` | A new policy version is created (settings stored) |
| `webhook_endpoint.created`, `.updated`, `.secret_rotated`, `.deleted` | Endpoint changes (host only, never the URL path; never the secret) |
| `signing_key.registered`, `.retired` | The platform's attestation signing keys |

Columns: `at_ms`, `action`, `partner_id`, `actor_type` (`api_key` | `system`), `actor_id`, `request_id`,
`target_type`, `target_id`, `details`. Written in the same transaction as the change. The database refuses
UPDATE, DELETE and TRUNCATE. Read it with `python scripts/list_audit.py`.

Not audited: device registrations and SDK session tokens (operational, one per device or call).

## 4. Alerts (`ops/prometheus/alerts.yml`)

All thresholds are PLACEHOLDERS until real traffic is measured.

| Alert | Fires when | For |
| :---- | :---- | :---- |
| `CertivoApiDown` | Prometheus cannot scrape the API | 2 min |
| `CertivoHighErrorRate` | 5xx share above 5%, with at least 0.2 requests/s | 5 min |
| `CertivoPacketIngestLagHigh` | p95 lag of live packets above 10 s | 5 min |
| `CertivoAttestationSigningFailing` | Any signer failure in 10 minutes | 1 min |

Test them: `promtool test rules ops/prometheus/alerts_test.yml`.
