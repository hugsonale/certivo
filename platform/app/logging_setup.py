"""Structured logging (P0-13, docs/adr/0019).

Every log line is one JSON object with a timestamp, level, logger name, message and the request ID of
the request that caused it. Two rules are enforced here rather than left to each caller:

  1. A log line never carries a secret. Values under suspicious names (token, secret, signature,
     authorization...) are replaced, and anything shaped like one of our keys or a Bearer token is
     scrubbed from messages and tracebacks.  Callers should still never log secrets; this is the net.
  2. A log line never carries media or biometric data. We never hold any, so nothing here can leak it.

This module imports nothing else from the app, so any other module may import it.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# The request being served, set by RequestContextMiddleware. Sync endpoints run in a worker thread
# that is given a copy of the context, so the ID is visible in their logs too.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

REDACTED = "[redacted]"
_MAX_STRING = 2000
_MAX_TRACEBACK = 6000

# A field NAME containing any of these has its value replaced, whatever the value looks like.
_SENSITIVE_NAME = re.compile(
    r"authorization|token|secret|password|passwd|signature|api[_-]?key|private|credential|cookie",
    re.IGNORECASE)

# A name ending like this holds an IDENTIFIER (api_key_id, session_token_id), which is public and is
# exactly what you need in a log to know which credential was used. Its VALUE is still scrubbed if it
# is shaped like a credential, so a secret mistakenly put in such a field is caught as well.
_IDENTIFIER_SUFFIXES = ("_id", "_ids", "-id")

# Things that look like our credentials, wherever they appear inside text.
_SECRET_SHAPES = (
    re.compile(r"\bcvk_[A-Za-z0-9_\-]{8,}"),              # partner API key (app/security.py)
    re.compile(r"\bskt_[A-Za-z0-9_\-]{8,}"),              # SDK session token
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}"),  # any Authorization: Bearer value
)

# Attributes every LogRecord has; anything else on a record was added with `extra=` and is logged.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def scrub(text: str) -> str:
    """Replace anything shaped like a credential inside free text."""
    for shape in _SECRET_SHAPES:
        text = shape.sub(REDACTED, text)
    return text


def _clean(value: Any, name: str = "") -> Any:
    """Make a value safe and JSON-friendly: redact by name, scrub strings, cap sizes."""
    if name and _SENSITIVE_NAME.search(name) and not name.endswith(_IDENTIFIER_SUFFIXES):
        return REDACTED
    if isinstance(value, str):
        value = scrub(value)
        return value if len(value) <= _MAX_STRING else value[:_MAX_STRING] + "...[truncated]"
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _clean(v, str(k)) for k, v in list(value.items())[:50]}
    if isinstance(value, list | tuple | set | frozenset):
        return [_clean(v) for v in list(value)[:50]]
    return scrub(str(value))[:_MAX_STRING]


def _clean_traceback(text: str) -> str:
    """A traceback keeps its START (where it began) and its END (the error itself, which matters most);
    only the middle is dropped when it is very long. Scrubbed first, so a credential cut in half by
    the trimming can never survive."""
    text = scrub(text)
    if len(text) <= _MAX_TRACEBACK:
        return text
    return text[:1000] + "\n...[middle of traceback omitted]...\n" + text[-(_MAX_TRACEBACK - 1000):]


def _trace_ids() -> dict[str, str]:
    """trace_id / span_id of the active OpenTelemetry span, if tracing is on (app/tracing.py)."""
    try:
        from opentelemetry import trace
    except ImportError:
        return {}
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return {}
    return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Field order is fixed so lines are easy to read and diff."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds")
                  .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": _clean(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        entry.update(_trace_ids())
        for key, value in vars(record).items():
            if key in _STANDARD_ATTRS or key == "request_id" or key.startswith("_"):
                continue
            entry[key] = _clean(value, key)
        if record.exc_info:
            entry["exc"] = _clean_traceback(self.formatException(record.exc_info))
        elif record.exc_text:
            entry["exc"] = _clean_traceback(record.exc_text)
        return json.dumps(entry, separators=(",", ":"), default=str)


class TextFormatter(logging.Formatter):
    """Human-readable lines for a developer's terminal (CERTIVO_LOG_FORMAT=text). Same scrubbing."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%H:%M:%S.%f")[:-3]
        request_id = getattr(record, "request_id", None) or request_id_var.get() or "-"
        extras = " ".join(f"{k}={_clean(v, k)}" for k, v in vars(record).items()
                          if k not in _STANDARD_ATTRS and k != "request_id" and not k.startswith("_"))
        line = f"{ts} {record.levelname:<7} [{request_id}] {record.name}: {_clean(record.getMessage())}"
        if extras:
            line += " " + extras
        if record.exc_info:
            line += "\n" + _clean_traceback(self.formatException(record.exc_info))
        return line


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever sys.stderr is at the moment of each write (so test capture works)."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property  # type: ignore[override]
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:  # StreamHandler.__init__ assigns it; ignored on purpose
        pass


_OUR_HANDLER_FLAG = "_certivo_handler"
_CHATTY_LIBRARIES = ("httpx", "httpcore", "urllib3", "botocore", "boto3", "hpack")


def configure_logging(level: str = "INFO", fmt: str = "json", handler: logging.Handler | None = None) -> None:
    """Install the Certivo handler on the root logger. Safe to call many times: it never stacks
    handlers, and it leaves any other handler (pytest's, for example) alone."""
    root = logging.getLogger()
    ours = next((h for h in root.handlers if getattr(h, _OUR_HANDLER_FLAG, False)), None)
    if handler is not None:
        if ours is not None:
            root.removeHandler(ours)
        ours = handler
        setattr(ours, _OUR_HANDLER_FLAG, True)
        root.addHandler(ours)
    elif ours is None:
        ours = _StderrHandler()
        setattr(ours, _OUR_HANDLER_FLAG, True)
        root.addHandler(ours)
    ours.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.setLevel(level.upper())

    # These libraries log the full URL of every request they make at INFO. Our webhook sender uses
    # httpx, and a partner's webhook URL may carry a secret token in its path or query string, which
    # our scrubber cannot recognise. Keep them quiet unless something is actually wrong.
    for name in _CHATTY_LIBRARIES:
        logging.getLogger(name).setLevel(max(logging.WARNING, logging.getLevelName(level.upper())))

    # uvicorn installs its own plain-text handlers. Route its server messages through ours, and
    # silence its access log: app/observability.py writes one structured access line per request.
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
