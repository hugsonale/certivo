"""Regenerate docs/spec/test-vectors/canonical-json-v1.json (cross-language contract, P0-22).
Run from platform/:  python scripts/gen_canonical_corpus.py

Why this exists: the score-packet vector is ONE packet. It cannot catch an SDK that escapes a quote
differently, or sorts `a_b` before `a1`, or mishandles the largest allowed integer. This file holds many
small cases, including inputs that must be REFUSED, and every SDK language must match every one.
Deterministic on purpose (a tiny generator of its own, not `random`): the file only changes when the
canonical profile changes."""
import json
import pathlib
import sys

sys.path.insert(0, ".")
from app.crypto import CanonicalizationError, canonical_json  # noqa: E402

MAX_INT = 2**53 - 1
PRINTABLE = "".join(chr(c) for c in range(0x20, 0x7F))


class Gen:
    """xorshift64*: the same numbers on every machine and every Python version."""

    def __init__(self, seed: int):
        self.s = seed & (2**64 - 1)

    def next(self) -> int:
        x = self.s
        x ^= x >> 12
        x ^= (x << 25) & (2**64 - 1)
        x ^= x >> 27
        self.s = x
        return (x * 0x2545F4914F6CDD1D) & (2**64 - 1)

    def below(self, n: int) -> int:
        return self.next() % n

    def key(self) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789_"
        return "".join(alphabet[self.below(len(alphabet))] for _ in range(1 + self.below(6)))

    def text(self) -> str:
        return "".join(PRINTABLE[self.below(len(PRINTABLE))] for _ in range(self.below(12)))

    def integer(self) -> int:
        choices = [0, 1, -1, MAX_INT, -MAX_INT, self.below(10**13), -self.below(10**13), self.below(1000)]
        return choices[self.below(8)]

    def value(self, depth: int):
        kind = self.below(4 if depth > 0 else 2)
        if kind == 0:
            return self.integer()
        if kind == 1:
            return self.text()
        if kind == 2:
            return [self.value(depth - 1) for _ in range(self.below(4))]
        return {self.key(): self.value(depth - 1) for _ in range(self.below(5))}


FIXED = [
    ("empty object", {}),
    ("empty array", []),
    ("zero", {"a": 0}),
    ("negative", {"a": -1}),
    ("largest allowed integer", {"a": MAX_INT}),
    ("smallest allowed integer", {"a": -MAX_INT}),
    ("a millisecond timestamp", {"t": 1760000004000}),
    ("key order: underscore, digit, letter",
     {"a_b": 1, "a1": 2, "ab": 3, "a": 4, "_": 5, "0": 6, "9": 7, "z": 8}),
    ("nested objects are sorted too", {"b": {"d": 1, "c": 2}, "a": {"y": [3, 2, 1], "x": {}}}),
    ("arrays keep their order", {"a": [3, 1, 2, [9, 8], {"z": 1, "y": 2}]}),
    ("a double quote in a string", {"a": 'say "hi"'}),
    ("a backslash in a string", {"a": "C:\\path\\file"}),
    ("a quote and a backslash together", {"a": '\\"'}),
    ("a string that is only a space", {"a": " "}),
    ("every printable character", {"a": PRINTABLE}),
    ("slash and tilde are not escaped", {"a": "a/b~c"}),
    ("an empty string", {"a": ""}),
    ("the longest allowed key", {"k" * 64: 1}),
    ("strings that look like numbers stay strings", {"a": "123", "b": "-0", "c": "true", "d": "null"}),
    ("a whole packet shape", {"v": 1, "seq": 0, "explanation": {"reason_codes": ["x"], "signal_milli": {}}}),
]

REJECTED = [
    ("a float", {"a": 1.5}),
    ("a small float", {"a": 0.1}),
    ("true", {"a": True}),
    ("false", {"a": False}),
    ("null", {"a": None}),
    ("a non-ASCII letter", {"a": "caf\u00e9"}),
    ("a tab", {"a": "tab\t"}),
    ("a newline", {"a": "line\nbreak"}),
    ("the DEL character", {"a": "del\x7f"}),
    ("an upper-case key", {"A": 1}),
    ("a key with a dash", {"a-b": 1}),
    ("an empty key", {"": 1}),
    ("a 65-character key", {"k" * 65: 1}),
    ("an integer just above the limit", {"a": MAX_INT + 1}),
    ("an integer just below the limit", {"a": -MAX_INT - 1}),
    ("a bad value deep inside", {"a": [{"b": {"c": 1.5}}]}),
    ("a bad key deep inside", {"a": [{"B": 1}]}),
]


def build() -> dict:
    gen = Gen(20261028)
    accepted = list(FIXED) + [(f"generated {i}", gen.value(4)) for i in range(150)]
    cases = []
    for name, value in accepted:
        raw = canonical_json(value)
        cases.append({"name": name, "value": value, "canonical_utf8": raw.decode(),
                      "canonical_bytes_hex": raw.hex()})
    for name, value in REJECTED:
        try:
            canonical_json(value)
        except CanonicalizationError:
            continue
        raise AssertionError(f"expected the canonical profile to refuse: {name}")
    return {
        "description": (
            "Cases for the canonical JSON profile (BUILD_SPEC_0 section 4). For each entry in `cases`, "
            "encoding `value` must give exactly `canonical_utf8` (and these bytes in hex). For each "
            "entry in `rejected`, encoding `value` must FAIL. Every SDK language must match every case."
        ),
        "cases": cases,
        "rejected": [{"name": name, "value": value} for name, value in REJECTED],
    }


if __name__ == "__main__":
    folder = pathlib.Path("../docs/spec/test-vectors")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "canonical-json-v1.json").write_text(json.dumps(build(), indent=1) + "\n")
    print("wrote", folder / "canonical-json-v1.json")
