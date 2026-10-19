"""Check that the configured signing key works, without touching the database.

    python scripts/check_signer.py

Run it after setting up a new key (see docs/engineering/KEY_ROTATION.md). It signs a test payload with
the configured signer, verifies the signature, and prints the key id and public key. Exit code 0 = OK.
"""
import sys

sys.path.insert(0, ".")

from app.attestation import load_signer, verify_attestation  # noqa: E402
from app.config import Settings  # noqa: E402

if __name__ == "__main__":
    signer = load_signer(Settings())
    sample = signer.sign_attestation({"v": 2, "type": "signer_check", "key_id": signer.key_id})
    if not verify_attestation(sample, signer.public_key):
        print("FAILED: the signature does not verify with the published public key")
        sys.exit(1)
    print(f"OK  key_id={signer.key_id}  public_key={signer.public_key}")
