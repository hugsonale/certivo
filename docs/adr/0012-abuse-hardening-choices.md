# ADR 0012: Abuse hardening: what we chose, and what we knowingly left for later

- **Date:** 2026-10-11
- **Status:** Accepted
- **Decision register / step IDs:** P0-06, P0-14, P1-17

## Context

Step P0-06 turns the authentication rules in `docs/spec/base/02` into code: scoped keys, expiring tokens, rate limits, size limits, timeouts, security headers and browser access rules. Several choices trade completeness now for simplicity, and the trade-offs should be written down.

## Decisions

1. **Scopes with a safe backfill.** Keys carry scopes. Keys that already existed were given every scope by a migration, so nothing broke. A key can never grant a scope it does not hold, and managing keys needs `keys:admin`.
2. **"Revocation" has four meanings, all immediate:** revoking an API key, revoking a device, ending a session (which kills its SDK token), and the token's own expiry. There is no separate "revoke this token" endpoint, because ending the session already does it.
3. **Rate limits are counted inside one server process.** Token buckets in memory, per API key, per SDK session, and for failed sign-ins per network address and per credential prefix. **Limitation:** with several processes or servers each counts separately, so the real limit is the setting times the number of processes. A shared Redis-backed limiter replaces it in a later step (P0-14). Step P0-07 introduces Redis for webhook delivery but does not move the limiter. All numbers are placeholders. `X-Forwarded-For` is trusted only when `trusted_proxy_hops` says how many proxies are in front, so the header cannot be used to dodge limits (and a real proxy does not make every caller look like one address).
4. **Size and speed limits.** Bodies over 64 KiB (placeholder) are refused with 413 before authentication, including bodies that only reveal their size while streaming. A body that stalls for 10 seconds (placeholder) gets 408. Each database statement is limited to 5 seconds (placeholder). **We did not add an overall deadline for a whole request.** Endpoints run in worker threads that cannot be cancelled safely, and a client that gave up could retry an action that had in fact completed. Revisit when the design changes.
5. **Security headers on every response**, including errors. The interactive docs exist only in dev.
6. **One global list of browser origins**, for the SDK endpoints only. Exact `https://` origins; wildcards and plain `http` only in dev; the app refuses to start with an unsafe list. The partner API is never opened to browsers.

## Consequences

- Until the shared limiter (P0-14) exists, rate limits are weaker than they look when more than one process runs. Production deployment (P1-17) must run a single process per limiter or wait for the shared limiter.
- Because the origin list is global, any listed partner's web page may call any session's SDK endpoints from a browser. A valid session token is still required, so this is a limited exposure. Per-partner origin lists (the session in the URL identifies the partner, since a CORS preflight carries no credentials) are a later improvement.
- Placeholder numbers need replacing from measured traffic (P0-27, P1-20).
- A partner can revoke its own only admin key and must then ask Certivo staff for a new one.
