# 06. Audit log and analytics

## In plain words

Two different questions need two different answers.

- **Audit log: "who did what, and when?"** A permanent, append-only diary of important actions (a key was
  created, a policy changed, a session ended, consent was withdrawn). It exists for accountability and
  investigations. It names actions and IDs, never personal data.
- **Analytics: "how is the integration doing?"** Totals and averages across many calls, for a partner's
  dashboard. It never shows an individual person's data.

## 1. Audit log

### What is recorded

| Category | Events |
|---|---|
| API keys | `api_key.created`, `api_key.revoked` |
| Devices | `device.registered`, `device.revoked` |
| Policies | `policy.created` |
| Webhooks | `webhook_endpoint.created`, `webhook_endpoint.deleted`, `webhook_endpoint.secret_rotated`, `webhook_endpoint.disabled` |
| Continuous sessions (Security Architecture, Table 8.1) | `session.started`, `session.ended`, `session.paused`, `session.resumed`, `session.confidence_dropped`, `attestation.signed` |
| Consent | `consent.granted`, `consent.declined`, `consent.withdrawn` |
| Platform keys | `signing_key.rotated`, `signing_key.revoked` |
| Trusted Device Layer (Security Architecture, Table 8.1; Privacy Architecture, section 4) | `trusted_device.issued`, `trusted_device.validated`, `trusted_device.revoked`, `device_switch.detected` |

All of this is **Planned (P0-13)** except the Trusted Device Layer events, which arrive with that layer
(P1-02 to P1-06). Nothing is audit-logged yet.

### Each entry

| Field | Meaning |
|---|---|
| `id` | `aud_` plus 32 hex |
| `created_at_ms` | When it happened |
| `partner_id` | Whose action or data; empty for platform-level events |
| `actor_type` | `api_key`, `sdk_session`, `system` or `dashboard_user` |
| `actor_id` | The key ID, session ID or user ID. Never the secret itself |
| `event_type` | From the table above |
| `subject_type`, `subject_id` | What was acted on, for example `policy` and `pol_...` |
| `request_id` | Links to the request that caused it |
| `metadata` | A small object of allowed fields only (see rules) |

### Rules

1. **Append-only.** The application never updates or deletes an entry. In production the database account the
   app uses is also not allowed to (Planned, P1-17).
2. **No personal data, no secrets, no free text** in `metadata`: only IDs, enum words and small integers. A
   test checks every event type against an allow-list of fields.
3. **High-volume events** such as `trusted_device.validated` may be summarised per minute rather than one
   entry per check, but never dropped without a count.
4. **A partner reads only its own entries** through `GET /v1/audit-logs` (scope `audit:read`), filtered by
   `event_type` and `since_ms`, paged as in document 01.
5. **Retention is not set here.** The period is a privacy and legal decision (P0-52, P1-18). Until then entries
   are kept; none are deleted.

| Method | Path | Status |
|---|---|---|
| GET | `/v1/audit-logs` | Planned (P0-13) |

## 2. Analytics for partners

Aggregates only, grouped by time, `use_case`, and (where relevant) SDK version and device tier.

| Method | Path | Returns | Status |
|---|---|---|---|
| GET | `/v1/analytics/sessions` | Counts: sessions started and ended, participants observed, `reject` transitions, paused sessions; average coverage | Planned (P1-11) |
| GET | `/v1/analytics/call-quality` | Resource overhead and inference time (p50 and p95) by device tier and SDK version, taken from SDK telemetry | Planned (P1-11) |

The partner dashboard shows call-quality impact **beside** decision analytics, because a partner's first
question is "does this hurt my calls?" (UX Specification, section 5.1; PRD FR-6.4).

### SDK telemetry (where call-quality numbers come from)

`POST /internal/v1/sessions/continuous/{session_id}/telemetry` (SDK token), Planned (P0-27). Whole numbers only:

| Field | Meaning |
|---|---|
| `sdk_version`, `sdk_platform` | Which build, and `web`, `ios` or `android` |
| `device_tier` | A coarse bucket, for example `low`, `mid`, `high`. Never a model name or identifier |
| `cpu_milli` | Share of one CPU core used, in thousandths |
| `memory_kb` | Memory used by the SDK |
| `bandwidth_bps` | Extra network traffic from verification |
| `inference_ms_p95` | Time to score one interval |
| `buffered_packets` | Packets waiting to upload |

**No device fingerprinting.** Telemetry must not make a device recognisable across platforms (Privacy
Architecture, section 3).

### Internal metrics versus partner analytics

Internal operations metrics (request rates, error rates, latency, queue depth) are for us and use the
monitoring stack (P0-13). They are not partner data and contain no personal data either.

## 3. Decisions for you to confirm

1. Audit entries are kept until the privacy review sets a period; nothing is deleted meanwhile.
2. Device tier in telemetry is a coarse bucket, never a device model.
3. High-volume validation events may be counted per minute instead of logged one by one.
