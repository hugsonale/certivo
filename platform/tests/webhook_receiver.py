"""A stand-in for a partner's server, used by the webhook tests.

It is a real HTTP(S) server on localhost. It records every request, can be told how to answer
(status, delay, headers, body), and, when given the signing secret, behaves like a careful partner:
it rejects bad signatures, stale timestamps and replayed event IDs.
"""
from __future__ import annotations

import json
import ssl
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.webhook_verify import ReplayGuard, verify_signature


@dataclass
class Reply:
    status: int = 200
    delay_s: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b"ok"


@dataclass
class Captured:
    path: str
    headers: dict[str, str]  # keys lower-cased
    body: bytes

    @property
    def json(self) -> dict:
        return json.loads(self.body)


class Receiver:
    def __init__(self, *, tls: ssl.SSLContext | None = None, verify_secret: str | None = None,
                 clock=lambda: int(time.time() * 1000)):
        self.requests: list[Captured] = []
        self.accepted: list[Captured] = []   # passed the careful-partner checks (if enabled)
        self.rejected: list[tuple[int, Captured]] = []
        self.script: list[Reply] = []        # used once each, in order; then `default`
        self.default = Reply()
        self.verify_secret = verify_secret
        self.clock = clock
        self.guard = ReplayGuard()
        self._tls = tls
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 (name required by http.server)
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                captured = Captured(self.path, {k.lower(): v for k, v in self.headers.items()}, body)
                with outer._lock:
                    outer.requests.append(captured)
                    reply = outer.script.pop(0) if outer.script else outer.default
                verdict = outer._careful_partner_check(captured)
                if verdict:
                    with outer._lock:
                        outer.rejected.append((verdict, captured))
                    reply = Reply(status=verdict)
                elif reply.status < 300:  # handled successfully: only now remember the event ID
                    with outer._lock:
                        outer.accepted.append(captured)
                        if outer.verify_secret is not None:
                            outer.guard.record(captured.headers.get("certivo-event-id", ""), outer.clock())
                if reply.delay_s:
                    time.sleep(reply.delay_s)
                try:
                    self.send_response(reply.status)
                    for name, value in reply.headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(reply.body)))
                    self.end_headers()
                    self.wfile.write(reply.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the sender gave up (for example, a timeout test)

            def log_message(self, *args):
                pass

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # a client that hangs up mid-handshake is part of some tests

        self._server = Server(("127.0.0.1", 0), Handler)
        if tls is not None:
            self._server.socket = tls.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _careful_partner_check(self, captured: Captured) -> int | None:
        if self.verify_secret is None:
            return None
        now = self.clock()
        signature = captured.headers.get("certivo-signature", "")
        if not verify_signature(self.verify_secret, signature, captured.body, now):
            return 401  # bad signature, or a timestamp outside the replay window
        if self.guard.is_duplicate(captured.headers.get("certivo-event-id", ""), now):
            return 409  # we have already acted on this event
        return None

    def start(self) -> Receiver:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def url(self, path: str = "/hook", scheme: str = "http", host: str = "127.0.0.1") -> str:
        return f"{scheme}://{host}:{self.port}{path}"
