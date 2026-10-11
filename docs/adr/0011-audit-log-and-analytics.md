# ADR 0011: Audit log and analytics are separate

- **Date:** 2026-10-11
- **Status:** Accepted
- **Decision register / step IDs:** P0-05, P0-13, P1-11

## Context

The suite requires audit logging and partner analytics but defines neither. Mixing them risks personal data leaking into logs or partners seeing individuals.

## Options considered

1. **One combined event stream:** less to build, but mixes accountability with reporting.
2. **An append-only audit log of actions and IDs, and separate aggregate-only analytics.**

## Decision

Option 2. Audit entries name actions and IDs only (no personal data, secrets or free text), are never updated or deleted by the app, and are readable only by their own partner. Analytics are aggregates and SDK telemetry with coarse device buckets, never device identifiers.

## Consequences

Retention periods are not set here; they await the privacy review. High-volume validation events may be counted per minute. Partner dashboards read analytics, never the audit log.
