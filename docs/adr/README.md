# Architecture Decision Records (ADRs)

An ADR is a short note recording one significant decision: what we faced, what we chose, and what follows from it. Future us reads it to understand why something is the way it is.

**When to write one:** any decision that is hard to reverse, affects more than one part of the system, changes a document in the spec suite, or settles an item in the Master Build Guide's decision register (D-01, D-02, ...).

**How:** copy `0000-template.md` to `NNNN-short-title.md` using the next free number, fill it in, and add a row below. Statuses: Proposed, Accepted, Superseded. Never delete an old ADR; supersede it with a new one.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-record-decisions-as-adrs.md) | Record decisions as ADRs | Accepted |
| [0002](0002-freeze-prototype-and-rebuild.md) | Freeze the prototype and rebuild on a new branch | Accepted |
| [0003](0003-signing-and-canonical-json.md) | Ed25519 signatures over restricted canonical JSON | Accepted for the backend; browser support unverified |
| [0004](0004-sdk-credentials.md) | Partner API keys and per-session SDK tokens | Accepted for Phase 0 |
| [0005](0005-migrations-and-postgres.md) | Alembic migrations, and rules that keep SQLite and Postgres in step | Accepted |
| [0006](0006-api-conventions-and-error-envelope.md) | API conventions and one error shape | Accepted |
| [0007](0007-authentication-model.md) | Authentication model: scoped keys, short-lived SDK tokens, and what Tier 3 means | Accepted (Tier 3 meaning needs privacy review) |
| [0008](0008-policy-engine-rules.md) | Policy engine rules: effective confidence, fallback behaviour, visibility | Accepted; visibility Proposed |
| [0009](0009-consent-enforced-and-device-signed.md) | Consent is enforced by the server and signed by the device | Accepted |
| [0010](0010-webhook-delivery-contract.md) | Webhook delivery contract | Accepted |
| [0011](0011-audit-log-and-analytics.md) | Audit log and analytics are separate | Accepted |
| [0012](0012-abuse-hardening-choices.md) | Abuse hardening: what we chose, and what we knowingly left for later | Accepted |
| [0013](0013-webhook-delivery-design.md) | Webhook delivery design | Accepted; two extra events Proposed |
