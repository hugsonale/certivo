"""A tiny stand-in for a partner's server, to try webhooks on your own PC.

    python scripts/demo_webhook_receiver.py whsec_YOUR_SECRET [port]

It does what a careful partner should: checks the signature and the timestamp, ignores an event it
has already handled, and only remembers an event after handling it. Press Ctrl+C to stop.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, ".")
from app.webhook_verify import ReplayGuard, verify_signature  # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit("usage: python scripts/demo_webhook_receiver.py whsec_YOUR_SECRET [port]")
SECRET = sys.argv[1]
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
guard = ReplayGuard()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        now = int(time.time() * 1000)
        event_id = self.headers.get("Certivo-Event-Id", "")
        if not verify_signature(SECRET, self.headers.get("Certivo-Signature", ""), body, now):
            print("REJECTED  bad signature, wrong secret, or message too old", flush=True)
            code = 401
        elif guard.is_duplicate(event_id, now):
            print(f"IGNORED   {event_id} was already handled (a replay or a retry)", flush=True)
            code = 409
        else:
            event = json.loads(body)
            print(f"ACCEPTED  {event['type']}  id={event['id']}  data={event['data']}", flush=True)
            guard.record(event_id, now)  # only after handling it
            code = 200
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


print(f"Listening on http://127.0.0.1:{PORT}/hook  (Ctrl+C to stop)", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
