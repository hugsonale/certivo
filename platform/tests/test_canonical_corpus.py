import importlib.util
import json
import pathlib

import pytest

from app.crypto import CanonicalizationError, canonical_json

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "docs/spec/test-vectors/canonical-json-v1.json"


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_corpus", pathlib.Path(__file__).resolve().parents[1] / "scripts/gen_canonical_corpus.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def test_published_canonical_corpus_is_current():
    """The file in docs/spec is the cross-language contract (the Web SDK checks it in CI).
    It must match what the code produces."""
    assert json.loads(CORPUS.read_text()) == _generator().build()


def test_the_real_canonicalizer_agrees_with_every_published_case():
    data = json.loads(CORPUS.read_text())
    assert len(data["cases"]) >= 150 and len(data["rejected"]) >= 15
    for case in data["cases"]:
        raw = canonical_json(case["value"])
        assert raw.decode() == case["canonical_utf8"], case["name"]
        assert raw.hex() == case["canonical_bytes_hex"], case["name"]
    for case in data["rejected"]:
        with pytest.raises(CanonicalizationError):
            canonical_json(case["value"])
