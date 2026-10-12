# Certivo base specifications

The 18-document suite says many things are "unchanged from Version 1.0". There was never a Version 1.0, so
these documents define those base parts for the flagship product (continuous verification of live calls).
They were written in step **P0-05** of the Master Build Guide. Read `../RECONCILIATION.md` for how each
item in the suite was settled.

| # | Document | Defines |
|---|---|---|
| 01 | [API conventions and errors](01-api-conventions-and-errors.md) | How every endpoint behaves, the error shape, the full list of error codes |
| 02 | [Authentication and keys](02-authentication-and-keys.md) | Who may call what: API keys, scopes, SDK tokens, device keys, the access matrix |
| 03 | [Policy engine](03-policy-engine.md) | How a score becomes accept, fallback or reject; partner settings; who sees what |
| 04 | [Consent service](04-consent-service.md) | How consent is recorded, enforced and withdrawn |
| 05 | [Webhooks](05-webhooks.md) | How Certivo notifies a partner's servers: endpoints, signing, retries, event list |
| 06 | [Audit log and analytics](06-audit-and-analytics.md) | What is recorded for accountability and what partners can see in aggregate |

## Status words used in every table

- **Implemented**: it exists in `platform/` and is covered by tests.
- **Planned (P0-xx)**: decided here, built in the named step of the Master Build Guide.
- **Proposed**: my recommendation, needs Jesutofunmi's explicit approval before it is built.

## These documents are checked against the code

`platform/tests/test_spec_consistency.py` fails the build if the error codes, endpoints, webhook events or
policy settings marked **Implemented** here differ from what the code really does (in either direction). So
when you add or remove one of these things, update the matching table in the same pull request.

## Numbers that are placeholders

Wherever a number appears (time limits, retry schedules, retention periods) it is either a value already in
the code, or marked **placeholder**. Placeholders are chosen to be safe, not validated, and must be replaced
with values from measured data or from the privacy review. Nothing here is a claim about performance.
