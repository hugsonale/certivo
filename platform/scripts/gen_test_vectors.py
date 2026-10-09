"""Regenerate docs/spec/test-vectors/score-packet-v1.json (cross-language contract).
Run from platform/:  python scripts/gen_test_vectors.py
The seed below is a PUBLIC TEST KEY. Never use it for anything real."""
import json
import pathlib
import sys

sys.path.insert(0, ".")
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from app.crypto import (  # noqa: E402
    SCORE_DOMAIN,
    b64u_encode,
    canonical_json,
    public_key_b64u,
    sign_message,
)

SEED = bytes(range(1, 33))
SESSION = "cs_00000000000000000000000000000001"
DEVICE = "dev_00000000000000000000000000000001"


def build() -> dict:
    key = Ed25519PrivateKey.from_private_bytes(SEED)
    packet = {
        "v": 1, "session_id": SESSION, "participant_reference": "alice", "device_id": DEVICE,
        "seq": 3, "interval_start_ms": 1760000003000, "interval_end_ms": 1760000004000,
        "confidence_milli": 912, "model_version": "edge-0.1.0",
        "explanation": {"reason_codes": ["consistent_motion", "stable_texture"],
                        "signal_milli": {"temporal": 940, "texture": 880}},
    }
    return {
        "description": "Ed25519 over SCORE_DOMAIN + canonical_json(packet). "
                       "Reproduce canonical_utf8 and signature in every SDK language.",
        "test_only_private_seed_hex": SEED.hex(),
        "public_key_b64u": public_key_b64u(key),
        "domain_utf8": SCORE_DOMAIN.decode(),
        "packet": packet,
        "canonical_utf8": canonical_json(packet).decode(),
        "canonical_bytes_hex": canonical_json(packet).hex(),
        "signature_b64u": sign_message(key, SCORE_DOMAIN, packet),
        "signature_b64u_len": len(b64u_encode(b"\0" * 64)),
    }


if __name__ == "__main__":
    out = pathlib.Path("../docs/spec/test-vectors/score-packet-v1.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build(), indent=2) + "\n")
    print("wrote", out)
