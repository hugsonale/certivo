"""Regenerate docs/spec/test-vectors/score-packet-v1.json (cross-language contract).
Run from platform/:  python scripts/gen_test_vectors.py
The seed below is a PUBLIC TEST KEY. Never use it for anything real."""
import hashlib
import hmac
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


def build_webhook() -> dict:
    secret = "whsec_test_only_not_a_real_secret"
    t_ms = 1760000004000
    body = (
        '{"id":"evt_00000000000000000000000000000001","type":"webhook.test",'
        '"created_at_ms":1760000004000,"api_version":"v1",'
        '"partner_id":"ptn_00000000000000000000000000000001","data":{}}'
    )
    sig = hmac.new(secret.encode(), f"{t_ms}.{body}".encode(), hashlib.sha256).hexdigest()
    return {
        "description": "HMAC-SHA256 over '<t>.<raw body>' using the signing secret, hex. "
                       "Header value: t=<t>,v1=<signature_hex>. TEST ONLY: the secret below is "
                       "public and not a real secret.",
        "test_only_secret": secret,
        "t_ms": t_ms,
        "raw_body": body,
        "signature_hex": sig,
        "header": f"t={t_ms},v1={sig}",
    }


if __name__ == "__main__":
    folder = pathlib.Path("../docs/spec/test-vectors")
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in (("score-packet-v1.json", build()), ("webhook-signature-v1.json", build_webhook())):
        (folder / name).write_text(json.dumps(data, indent=2) + "\n")
        print("wrote", folder / name)
