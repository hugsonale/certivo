# ADR 0009: Consent is enforced by the server and signed by the device

- **Date:** 2026-10-11
- **Status:** Accepted
- **Decision register / step IDs:** P0-05, P0-51

## Context

"No integration may bypass consent" is a Vision non-negotiable. A consent screen alone can be skipped by a careless or unscrupulous integration, or faked by a partner's server.

## Options considered

1. **Trust the partner to show the screen:** weakest.
2. **Record consent signed by the device and refuse packets without it:** a partner's server cannot fabricate it, and the check cannot be configured away.
3. **Verify consent only at audit time:** finds problems too late.

## Decision

Option 2. The SDK signs each consent decision with the device key. A score packet from a participant with no current granted `base_verification` consent is refused with `consent_required`. Two consent types are kept apart: base verification and the Trusted Device Layer. Records are append-only; withdrawal is immediate.

## Consequences

Consent is per person per platform and lasts until withdrawn or the wording needs fresh consent. Retention, erasure and the effect of withdrawal on trusted-device tokens are deferred to the privacy review and counsel.
