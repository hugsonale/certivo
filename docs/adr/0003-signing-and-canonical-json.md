# ADR 0003: Ed25519 signatures over restricted canonical JSON

- **Date:** 2026-10-09
- **Status:** Accepted for the backend. Browser support for Ed25519 is not yet verified (decision D-01).
- **Decision register / step IDs:** D-01, P0-00, P0-20, P0-22

## Context

Each device signs every score packet so the backend can check where it came from. The signature is computed over bytes, so the web, iOS and Android SDKs and the backend must all produce byte-identical bytes from the same packet. Ordinary JSON serialisation differs between languages, especially for floating-point numbers.

## Options considered

1. **Sign the raw JSON the sender produced:** simple, but verification depends on preserving exact bytes.
2. **Use a general canonical-JSON library in every language:** correct, but adds a dependency per platform.
3. **Define a small restricted JSON profile that is easy to reproduce by hand:** keys `[a-z0-9_]` sorted, no whitespace, integers and printable-ASCII strings only, no floats, booleans or nulls.

## Decision

Option 3, with Ed25519 and a domain prefix (`certivo.score.v1\n` for score packets, `certivo.attestation.v1\n` for attestations). Confidence is sent as an integer from 0 to 1000 (`confidence_milli`) instead of a float. A shared test vector in `docs/spec/test-vectors/` must be reproduced by every implementation.

## Consequences

This deviates from Doc 6, which describes confidence as a float from 0.0 to 1.0. Every SDK must pass the test vector before sending traffic. We still must verify Ed25519 support in WebCrypto on target browsers (step P0-20). If it is not widely supported, we add an `alg` field to the device record and allow ECDSA P-256 as well.
