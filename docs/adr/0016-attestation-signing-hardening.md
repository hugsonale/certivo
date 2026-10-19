# ADR 0016: Attestation signing hardening

- **Date:** 2026-10-18
- **Status:** Proposed (waiting for Jesutofunmi to approve; one decision needs an answer, see "Open decision")
- **Decision register / step IDs:** P0-10, P0-52, SDD 7.2, FR-4.1 (extended)

## Context

Until now the platform signed attestations with a private key read from an environment setting, published only that one public key, and failed the whole `end` request if signing failed. Four requirements: signing is a Cryptographic Service boundary behind a clean interface; the attestation covers the full session history; if the signer is down, the request is queued and retried (SDD 7.2, "a call that ends while this service is unavailable queues its attestation-signing request for retry rather than failing to produce a session record at all"); keys have IDs and rotation with old public keys kept published, and production keys come from a managed key service, never from environment files.

## Options considered

1. **Keep the key in the application, add rotation by config.** Simple, but the private key sits in the app's memory and settings, which is what the requirement forbids.
2. **A managed key service behind an interface.** The private key never reaches our process; the service only asks for a signature.
3. **Run our own signing microservice.** A clean boundary, but we would then have to protect that service's key ourselves.

## Decision

Option 2.

- **Interface.** `SigningBackend` (`app/signing.py`): the key's public half and `sign(message)`. `LocalKeyBackend` is for development and tests only. `AwsKmsBackend` keeps an Ed25519 key in AWS KMS (key spec `ECC_NIST_EDWARDS25519`). Production refuses to start with a key in its environment or with the local backend.
- **Signature format v2.** AWS KMS signs at most 4096 bytes per call, and an attestation can be larger, so v2 signs `domain + SHA-256(canonical payload)` (55 bytes). Partners verify with an ordinary Ed25519 check after one hash. v1 attestations keep verifying; the payload's `v` tells the verifier which form to use.
- **Full session history (FR-4.1 extended).** The payload now carries `outcome_counts` and a `history_sha256` per participant, and `history.root_sha256` over all of them. They commit to every scored interval, including each packet's device signature, without storing the intervals, which retention deletes first (ADR 0015).
- **Key IDs and rotation.** The `attestation_keys` table lists every key ever used and is published at `/.well-known/certivo-keys` with `status` and `retired_at_ms`. Rows are never deleted. Rotating = new KMS key + new `CERTIVO_ATTESTATION_KEY_ID` + restart; the first start adds the new key and marks the old one retired. A key ID can never be reused for a different key: the service refuses to start.
- **Queue and retry.** The record of a finished call always exists the moment it ends. If signing fails, the unsigned payload is stored with the call, `end` answers 202 with the coverage summary, and a worker task retries every 30 s with waits of 5 s, 10 s, 20 s ... up to 60 s. It never gives up. A queued attestation is signed by whichever key is active when it finally succeeds, and its payload names that key. `GET .../attestation` returns 200 when signed and 202 while queued.

## Open decision (needs your answer)

Your documents do not say which managed key service you will use. I built and tested the adapter for **AWS KMS** because it supports Ed25519 and the private key never leaves it. It was tested against a stand-in that enforces KMS's real rules, **not against a real AWS account**. To use it: create the key, give the service the `kms:Sign` and `kms:GetPublicKey` permissions on it, and add `boto3` to `requirements.txt` (not added yet, so CI and the dependency scan are unchanged). If you prefer Google Cloud KMS or Vault, only one small adapter class changes. **Until a managed backend is configured, production refuses to start.**

## Consequences

An outage of the key service delays attestations by minutes but never loses a record. Two workers may sign the same queued payload at once; Ed25519 signatures are deterministic, so the result is identical. The retired keys list grows forever by design. Chosen retry waits and the 60 s cap are placeholders to tune. Attestation retention is still undecided (P0-52).
