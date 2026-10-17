import json
import pathlib

import pytest

from app.crypto import (
    SCORE_DOMAIN,
    CanonicalizationError,
    canonical_json,
    sign_message,
    verify_message,
)

VECTORS = pathlib.Path(__file__).resolve().parents[2] / "docs/spec/test-vectors/score-packet-v1.json"


def test_canonical_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": 1, "a": {"d": [1, 2], "c": "x"}}) == b'{"a":{"c":"x","d":[1,2]},"b":1}'


@pytest.mark.parametrize("bad", [
    {"a": 1.5}, {"a": True}, {"a": None}, {"A": 1}, {"a-b": 1}, {"a": "caf\u00e9"},
    {"a": 2**60}, {"a": "tab\t"}, {"a": {1, 2}},
])
def test_canonical_rejects_non_profile_values(bad):
    with pytest.raises(CanonicalizationError):
        canonical_json(bad)


def test_sign_verify_roundtrip_and_tamper(app):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from app.crypto import public_key_b64u
    key = Ed25519PrivateKey.generate()
    pub = public_key_b64u(key)
    msg = {"a": 1, "b": "x"}
    sig = sign_message(key, SCORE_DOMAIN, msg)
    assert verify_message(pub, SCORE_DOMAIN, msg, sig)
    assert not verify_message(pub, SCORE_DOMAIN, {"a": 2, "b": "x"}, sig)
    assert not verify_message(pub, b"other.domain\n", msg, sig)  # domain separation
    assert not verify_message(pub, SCORE_DOMAIN, msg, "not-a-signature")


def test_published_test_vector_is_current():
    """The vector file in docs/spec is the cross-language contract; it must match the code."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gen", pathlib.Path(__file__).resolve().parents[1] / "scripts/gen_test_vectors.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert json.loads(VECTORS.read_text()) == gen.build()
