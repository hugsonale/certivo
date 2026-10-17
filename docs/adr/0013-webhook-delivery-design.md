# ADR 0013: Webhook delivery design

- **Date:** 2026-10-12
- **Status:** Accepted. The two extra events (`session.resumed`, `session.confidence_recovered`) remain Proposed and are not built.
- **Decision register / step IDs:** P0-07, P0-63, P0-14

## Context

Partners need to be told when something happens, reliably and safely. Delivering messages to other people's servers means handling failure (their server is down), trust (they must know it was us), duplicates, and abuse (someone registering a URL that points inside our network).

## Options considered

1. **Send from the request that caused the event:** simple, but a slow partner slows our API and a crash loses the event.
2. **Queue only (Redis) as the source of truth:** fast, but losing Redis loses events.
3. **Write the event to the database in the same transaction as the change, and let a worker deliver from the database; Celery and Redis only decide when to run.**

## Decision

Option 3.

- **Outbox.** An event row is saved with the change that caused it, so it exists exactly when the change was saved. The API never waits for a partner and does not even need Redis.
- **The database owns the schedule.** Each delivery stores its state and next-due time. A worker locks due deliveries with an atomic update and a one-time claim token. If a worker dies the lock expires; a slow worker that returns late finds its token replaced and does nothing.
- **At least once.** A rare crash after the partner answered but before we recorded it means a resend. Receivers must de-duplicate by event ID, **recording the ID only after handling succeeds**. A reference implementation ships in the repo.
- **Signed and replay-limited.** HMAC-SHA256 over the timestamp and exact body, freshly signed on every attempt, with a 5-minute window for receivers. Two secrets sign during rotation.
- **Secrets are encrypted, not hashed**, because we must use them. The key lives outside the database. Outside dev the app refuses to start without it; dev uses a fixed, insecure fallback.
- **SSRF defences.** Public addresses only; connect to the address we checked rather than the name; never follow redirects; never read or store a partner's reply; only short error codes are kept. Private targets are allowed only by a dev flag that the app refuses to start with elsewhere.
- **Retries** follow a configurable schedule (default seven attempts over about 21 hours), then the delivery is `dead` until retried by hand. Every attempt is logged.

## Not done (deliberately)

- Automatically disabling an endpoint that keeps failing (Proposed in base/05).
- `session.resumed` and `session.confidence_recovered` events, awaiting approval.
- A shared Redis rate limiter (step P0-14).
- Production key management for the webhook secret key (step P0-63).

## Consequences

The worker needs Redis and Celery in production, but a Redis outage only delays deliveries. Beat (the timer) is embedded in the worker, so run exactly one worker with it until we split them. Celery is awkward on Windows, so local Windows development uses Docker or the simple loop script. Events that happened before an endpoint existed are never sent to it.
