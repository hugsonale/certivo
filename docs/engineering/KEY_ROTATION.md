# Rotating the attestation signing key

Rotate on a schedule decided in the security review (P0-52), and immediately if a key may be exposed.
Old attestations keep verifying: every key ever used stays published at `/.well-known/certivo-keys`.

## Steps (AWS KMS)

1. **Create the new key** in KMS: key spec `ECC_NIST_EDWARDS25519`, key usage `SIGN_VERIFY`. Give the platform's role `kms:Sign` and `kms:GetPublicKey` on it.
2. **Check it before switching.** With the new settings in place, run `python scripts/check_signer.py`. It must print `OK` and the new public key.
3. **Pick a new key id** that has never been used, for example `att-2027-01`. Never reuse one: the service refuses to start if it is attempted.
4. **Deploy** with `CERTIVO_ATTESTATION_KEY_ID=att-2027-01` and `CERTIVO_ATTESTATION_KMS_KEY_ID=<new key>`.
5. **Confirm:** `GET /.well-known/certivo-keys` lists the new key as `active` and the previous one as `retired`. End a test call and verify its attestation.
6. **Keep the old KMS key** (do not delete or disable it for signing history). Disabling signing on it is fine; the public key is already published here.

An attestation that was waiting in the signing queue during a rotation is signed by the new key, and says so.

## If the signing service is down

Calls still end. Their attestations wait with `attestation_status: "pending"` and are signed automatically when the service returns. To see what is waiting: `SELECT session_id, attempts, last_error FROM session_attestations WHERE status = 'pending';`
