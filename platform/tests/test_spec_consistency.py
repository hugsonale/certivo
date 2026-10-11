"""The base specifications (docs/spec/base/) must match the code.

Anything a spec marks "Implemented" has to exist in the code, and anything the code does in these areas
has to be written down. If one of these tests fails, either the code or the spec is out of date.
"""
import hashlib
import hmac
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.policy import DEFAULT_POLICY_CONFIG

PLATFORM = Path(__file__).resolve().parents[1]
BASE = PLATFORM.parent / "docs" / "spec" / "base"
VECTORS = PLATFORM.parent / "docs" / "spec" / "test-vectors"
STATUS = re.compile(r"^(Implemented|Planned \(P[0-3]-\d{2}\)|Proposed)(\s|$|[;,.])")
DOCS = ["01-api-conventions-and-errors.md", "02-authentication-and-keys.md", "03-policy-engine.md",
        "04-consent-service.md", "05-webhooks.md", "06-audit-and-analytics.md"]


def split_row(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def read_tables(doc: str):
    """Yield every markdown table in a document as a list of dicts keyed by header text."""
    lines = (BASE / doc).read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines) - 1:
        if lines[i].startswith("|") and re.fullmatch(r"[\s|:-]+", lines[i + 1]):
            headers = split_row(lines[i])
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                cells = split_row(lines[j])
                if len(cells) == len(headers):
                    rows.append(dict(zip(headers, cells, strict=True)))
                j += 1
            yield headers, rows
            i = j
        else:
            i += 1


def table(doc: str, first_header: str) -> list[dict]:
    for headers, rows in read_tables(doc):
        if headers[0] == first_header:
            return rows
    raise AssertionError(f"No table starting with '{first_header}' in {doc}")


def unticked(cell: str) -> str:
    return cell.strip("`")


def app_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in (PLATFORM / "app").rglob("*.py"))


def test_every_status_cell_uses_the_agreed_words():
    checked = 0
    for doc in DOCS:
        for headers, rows in read_tables(doc):
            if "Status" in headers:
                for row in rows:
                    assert STATUS.match(row["Status"]), f"{doc}: bad status {row['Status']!r}"
                    checked += 1
    assert checked > 60


def test_error_catalogue_matches_the_code():
    rows = table("01-api-conventions-and-errors.md", "Code")
    codes = [unticked(r["Code"]) for r in rows]
    assert len(codes) == len(set(codes)), "duplicate error code in the catalogue"

    source = app_source()
    api_errors = re.findall(r'ApiError\(\s*(\d+),\s*"([a-z_]+)"', source)
    handler_codes = set(re.findall(r'_body\(\s*request,\s*"([a-z_]+)"', source))
    in_code = {code for _, code in api_errors} | handler_codes

    documented_implemented = {unticked(r["Code"]) for r in rows
                              if r["Status"].startswith("Implemented") and "<" not in r["Code"]}
    assert in_code == documented_implemented, (
        f"only in code: {sorted(in_code - documented_implemented)}; "
        f"only in the spec: {sorted(documented_implemented - in_code)}")

    # the HTTP status written in the spec must match the one in the code
    spec_http = {unticked(r["Code"]): r["HTTP"] for r in rows}
    for status, code in api_errors:
        assert spec_http[code] == status, f"{code}: spec says {spec_http[code]}, code says {status}"


def test_error_codes_are_the_promised_shape():
    for r in table("01-api-conventions-and-errors.md", "Code"):
        assert re.fullmatch(r"`[a-z_]+(<status>)?`", r["Code"]), r["Code"]


def test_access_matrix_matches_the_real_endpoints(app):
    rows = table("02-authentication-and-keys.md", "Method")
    spec = {(r["Method"], unticked(r["Path"])) for r in rows if r["Status"].startswith("Implemented")}
    listed_any = [(r["Method"], unticked(r["Path"])) for r in rows]
    assert len(listed_any) == len(set(listed_any)), "an endpoint is listed twice"

    real = {(method.upper(), path)
            for path, item in app.openapi()["paths"].items() for method in item}
    assert real == spec, (f"only in code: {sorted(real - spec)}; only in the spec: {sorted(spec - real)}")


def test_endpoints_documented_elsewhere_are_in_the_access_matrix():
    """Every endpoint named in documents 03 to 06 must also appear in the access matrix."""
    matrix = {(r["Method"], unticked(r["Path"])) for r in table("02-authentication-and-keys.md", "Method")}
    for doc in DOCS[2:]:
        for headers, rows in read_tables(doc):
            if headers[:2] == ["Method", "Path"]:
                for r in rows:
                    assert (r["Method"], unticked(r["Path"])) in matrix, f"{doc}: {r['Method']} {r['Path']}"


def test_webhook_events_match_the_code():
    rows = table("05-webhooks.md", "Event")
    documented = {unticked(r["Event"]) for r in rows if r["Status"].startswith("Implemented")}
    emitted = set(re.findall(r'_emit\(\s*db,\s*[^,]+,\s*"([a-z_]+\.[a-z_]+)"', app_source()))
    assert emitted == documented, f"in code: {sorted(emitted)}; documented: {sorted(documented)}"


def test_policy_settings_match_the_code():
    rows = table("03-policy-engine.md", "Setting")
    implemented = {unticked(r["Setting"]): r["Default"] for r in rows if r["Status"].startswith("Implemented")}
    assert set(implemented) == set(DEFAULT_POLICY_CONFIG)
    for key, default_text in implemented.items():
        assert int(default_text.split()[0]) == DEFAULT_POLICY_CONFIG[key], key


def verify_webhook(secret: str, header: str, raw_body: str, now_ms: int, tolerance_s: int = 300) -> bool:
    """Reference implementation of the receiver's check in docs/spec/base/05-webhooks.md section 3."""
    parts = [p.split("=", 1) for p in header.split(",")]
    t = next(int(v) for k, v in parts if k == "t")
    candidates = [v for k, v in parts if k == "v1"]
    if abs(now_ms - t) > tolerance_s * 1000:
        return False
    expected = hmac.new(secret.encode(), f"{t}.{raw_body}".encode(), hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, c) for c in candidates)


def test_webhook_signature_vector_and_reference_check():
    v = json.loads((VECTORS / "webhook-signature-v1.json").read_text())
    now = v["t_ms"] + 5_000
    assert v["header"] == f"t={v['t_ms']},v1={v['signature_hex']}"
    assert verify_webhook(v["test_only_secret"], v["header"], v["raw_body"], now)
    assert not verify_webhook(v["test_only_secret"], v["header"], v["raw_body"] + " ", now)  # tampered
    assert not verify_webhook("whsec_wrong", v["header"], v["raw_body"], now)  # wrong secret
    assert not verify_webhook(v["test_only_secret"], v["header"], v["raw_body"], v["t_ms"] + 301_000)  # replay
    rotating = f"t={v['t_ms']},v1={'0' * 64},v1={v['signature_hex']}"  # two values during rotation
    assert verify_webhook(v["test_only_secret"], rotating, v["raw_body"], now)


def test_webhook_vector_file_is_current():
    spec = importlib.util.spec_from_file_location("gen", PLATFORM / "scripts/gen_test_vectors.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert json.loads((VECTORS / "webhook-signature-v1.json").read_text()) == gen.build_webhook()


@pytest.mark.parametrize("doc", DOCS)
def test_every_spec_has_the_plain_words_section(doc):
    text = (BASE / doc).read_text(encoding="utf-8")
    assert "## In plain words" in text
