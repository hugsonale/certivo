"""Structured logging (P0-13): one JSON object per line, request IDs, and secrets never logged."""
import json
import logging
import sys

from app.logging_setup import (
    REDACTED,
    JsonFormatter,
    TextFormatter,
    configure_logging,
    request_id_var,
    scrub,
)
from tests.obs_support import FAKE_API_KEY, FAKE_SDK_TOKEN


def _record(message="hello", level=logging.INFO, exc_info=None, **extra):
    record = logging.LogRecord("certivo.test", level, __file__, 1, message, None, exc_info)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _format(**kwargs):
    return json.loads(JsonFormatter().format(_record(**kwargs)))


def test_a_line_is_one_json_object_with_the_basic_fields():
    line = JsonFormatter().format(_record("started"))
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["msg"] == "started"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "certivo.test"
    assert entry["ts"].endswith("Z") and "T" in entry["ts"]


def test_the_request_id_of_the_current_request_is_on_every_line():
    token = request_id_var.set("req_abc123")
    try:
        assert _format()["request_id"] == "req_abc123"
    finally:
        request_id_var.reset(token)
    assert "request_id" not in _format()


def test_an_explicit_request_id_wins_over_the_current_one():
    token = request_id_var.set("req_current")
    try:
        assert _format(request_id="req_explicit")["request_id"] == "req_explicit"
    finally:
        request_id_var.reset(token)


def test_extra_fields_are_included():
    entry = _format(status=404, route="/v1/policies/{policy_id}", duration_ms=12.5)
    assert entry["status"] == 404
    assert entry["route"] == "/v1/policies/{policy_id}"
    assert entry["duration_ms"] == 12.5


def test_fields_with_sensitive_names_are_redacted():
    entry = _format(authorization=f"Bearer {FAKE_API_KEY}", sdk_token="anything at all",
                    webhook_secret="s3cret", device_signature="sig", password="hunter2",
                    api_key="whatever", nested={"client_secret": "x", "ok": 1})
    for name in ("authorization", "sdk_token", "webhook_secret", "device_signature", "password", "api_key"):
        assert entry[name] == REDACTED, name
    assert entry["nested"] == {"client_secret": REDACTED, "ok": 1}


def test_credentials_are_scrubbed_from_messages_and_values():
    entry = _format(message=f"call failed for {FAKE_API_KEY} then {FAKE_SDK_TOKEN}",
                    note=f"header was Bearer {FAKE_API_KEY}")
    text = json.dumps(entry)
    assert FAKE_API_KEY not in text and FAKE_SDK_TOKEN not in text
    assert "cvk_" not in text and "skt_" not in text


def test_credentials_are_scrubbed_from_tracebacks():
    try:
        raise RuntimeError(f"boom with {FAKE_SDK_TOKEN}")
    except RuntimeError:
        entry = _format(message="failed", level=logging.ERROR, exc_info=sys.exc_info())
    assert "RuntimeError" in entry["exc"]
    assert FAKE_SDK_TOKEN not in json.dumps(entry)


def test_strange_values_never_break_logging():
    class Odd:
        def __repr__(self):
            return "<odd>"

    entry = _format(thing=Odd(), big="x" * 5000, items=list(range(500)))
    assert entry["thing"] == "<odd>"
    assert entry["big"].endswith("[truncated]") and len(entry["big"]) < 2100
    assert len(entry["items"]) == 50


def test_text_format_scrubs_too():
    line = TextFormatter().format(_record(f"using {FAKE_API_KEY}", status=500))
    assert FAKE_API_KEY not in line and "status=500" in line


def test_scrub_leaves_ordinary_text_alone():
    assert scrub("session cs_0123 ended in 4.2 s") == "session cs_0123 ended in 4.2 s"


def test_configure_logging_installs_one_handler_however_often_it_is_called():
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        configure_logging("INFO", "json")
        configure_logging("WARNING", "text")
        configure_logging("INFO", "json")
        ours = [h for h in root.handlers if getattr(h, "_certivo_handler", False)]
        assert len(ours) == 1
        assert isinstance(ours[0].formatter, JsonFormatter)
        assert all(h in root.handlers for h in before)  # other handlers (pytest's) are untouched
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_certivo_handler", False):
                root.removeHandler(handler)
        root.setLevel(logging.WARNING)


def test_the_installed_handler_writes_json_to_stderr(capsys):
    root = logging.getLogger()
    try:
        configure_logging("INFO", "json")
        logging.getLogger("certivo.test").info("hello stderr", extra={"status": 200})
        err = capsys.readouterr().err
        entry = json.loads(err.strip().splitlines()[-1])
        assert entry["msg"] == "hello stderr" and entry["status"] == 200
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_certivo_handler", False):
                root.removeHandler(handler)
        root.setLevel(logging.WARNING)


def test_a_long_traceback_keeps_its_ending_where_the_error_message_is():
    try:
        raise ValueError("start " + "x" * 9000 + f" {FAKE_API_KEY} THE_REAL_ENDING")
    except ValueError:
        entry = _format(message="failed", level=logging.ERROR, exc_info=sys.exc_info())
    assert entry["exc"].startswith("Traceback")
    assert "omitted" in entry["exc"] and entry["exc"].endswith("THE_REAL_ENDING")
    assert FAKE_API_KEY not in entry["exc"]


def test_identifiers_of_credentials_are_kept_because_they_are_public_and_needed():
    entry = _format(api_key_id="key_0123456789abcdef", session_token_id="tok_abc", api_key="cvk_whatever")
    assert entry["api_key_id"] == "key_0123456789abcdef"
    assert entry["session_token_id"] == "tok_abc"
    assert entry["api_key"] == REDACTED  # the credential itself is still redacted by name


def test_a_secret_put_in_an_identifier_field_by_mistake_is_still_scrubbed():
    entry = _format(api_key_id=FAKE_API_KEY)
    assert FAKE_API_KEY not in json.dumps(entry)


def test_libraries_that_log_full_request_urls_are_kept_quiet():
    """httpx logs every URL it calls at INFO; a partner's webhook URL can hold a secret token."""
    root = logging.getLogger()
    try:
        configure_logging("INFO", "json")
        for name in ("httpx", "httpcore", "urllib3"):
            assert not logging.getLogger(name).isEnabledFor(logging.INFO), name
            assert logging.getLogger(name).isEnabledFor(logging.WARNING), name
        assert logging.getLogger("certivo.anything").isEnabledFor(logging.INFO)
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_certivo_handler", False):
                root.removeHandler(handler)
        root.setLevel(logging.WARNING)
        for name in ("httpx", "httpcore", "urllib3"):
            logging.getLogger(name).setLevel(logging.NOTSET)
