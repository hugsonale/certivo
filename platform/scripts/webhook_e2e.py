"""End-to-end check of webhook delivery with a REAL Redis and a REAL Celery worker process.

    CERTIVO_DATABASE_URL=... CERTIVO_REDIS_URL=redis://localhost:6379/0 python scripts/webhook_e2e.py

It starts a stand-in partner server, starts the worker, then proves: a signed event arrives and
verifies; a failing partner is retried; a replayed message is rejected; a partner that keeps failing
ends in the dead-letter state and a manual retry delivers it. Exits non-zero on any failure.
Needs CERTIVO_ENV=dev and CERTIVO_WEBHOOK_ALLOW_PRIVATE_TARGETS=true (it talks to localhost).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, ".")
os.environ.setdefault("CERTIVO_ENV", "dev")
os.environ["CERTIVO_WEBHOOK_ALLOW_PRIVATE_TARGETS"] = "true"
os.environ["CERTIVO_WEBHOOK_RETRY_DELAYS_S"] = "1,1,1"
os.environ["CERTIVO_WEBHOOK_POLL_INTERVAL_S"] = "1"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.admin import create_partner  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine, make_session_factory, upgrade_to_head  # noqa: E402
from app.main import create_app  # noqa: E402
from app.webhook_verify import ReplayGuard, verify_signature  # noqa: E402


class Partner:
    """A careful partner: checks the signature and timestamp, ignores duplicates."""

    def __init__(self):
        self.secret = None
        self.fail_next = 0
        self.always_fail = False
        self.accepted, self.requests = [], []
        self.guard = ReplayGuard()
        partner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                headers = {k.lower(): v for k, v in self.headers.items()}
                partner.requests.append((headers, body))
                now = int(time.time() * 1000)
                if not verify_signature(partner.secret or "", headers.get("certivo-signature", ""), body, now):
                    code = 401
                elif partner.guard.is_duplicate(headers.get("certivo-event-id", ""), now):
                    code = 409
                elif partner.always_fail or partner.fail_next > 0:
                    partner.fail_next = max(0, partner.fail_next - 1)
                    code = 500  # we failed: do NOT remember this event, or the retry would be refused
                else:
                    partner.accepted.append(json.loads(body))
                    partner.guard.record(headers.get("certivo-event-id", ""), now)  # only after success
                    code = 200
                self.send_response(code)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/hook"


def wait_for(description, condition, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.25)
    raise SystemExit(f"FAILED: timed out waiting for {description}")


def check(description, ok):
    print(("  ok   " if ok else "  FAIL ") + description)
    if not ok:
        raise SystemExit(1)


def main():
    settings = Settings()
    upgrade_to_head(settings.database_url)
    app = create_app(settings)
    client = TestClient(app)
    with make_session_factory(make_engine(settings.database_url))() as db:
        _, key = create_partner(db, "E2E Partner")
    headers = {"Authorization": f"Bearer {key}"}

    partner = Partner()
    created = client.post("/v1/webhook-endpoints", headers=headers,
                          json={"url": partner.url, "event_types": ["*"]}).json()
    partner.secret = created["secret"]

    worker = subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "app.worker", "worker", "--beat", "-Q", "webhooks",
         "--concurrency=2", "--loglevel=warning", "--schedule", os.path.join(tempfile.mkdtemp(), "beat")])
    try:
        def pause():
            s = client.post("/v1/sessions/continuous", headers=headers,
                            json={"use_case": "default_video_call"}).json()
            client.post(f"/internal/v1/sessions/continuous/{s['id']}/pause",
                        headers={"Authorization": f"Bearer {s['sdk_token']}"}, json={"reason": "connectivity"})

        def deliveries(**params):
            return client.get("/v1/webhook-deliveries", headers=headers, params=params).json()["data"]

        print("1. a signed event is delivered")
        pause()
        wait_for("the first delivery", lambda: len(partner.accepted) == 1)
        check("partner accepted a verified session.paused event", partner.accepted[0]["type"] == "session.paused")
        wait_for("the log to say delivered", lambda: deliveries(status="delivered"))

        print("2. a failing partner is retried")
        partner.fail_next = 2
        pause()
        wait_for("the retried delivery", lambda: len(partner.accepted) == 2)
        check("it succeeded on the third attempt", max(d["attempt_count"] for d in deliveries()) == 3)

        print("3. a replayed message is rejected")
        headers_seen, body = partner.requests[0]
        replay = httpx.post(partner.url, content=body, headers={
            "Certivo-Signature": headers_seen["certivo-signature"],
            "Certivo-Event-Id": headers_seen["certivo-event-id"]})
        check("the same message sent again gets 409", replay.status_code == 409)
        check("and was not acted on twice", len(partner.accepted) == 2)

        print("4. a partner that keeps failing ends dead, and a manual retry delivers it")
        partner.always_fail = True
        pause()
        wait_for("the dead-letter state", lambda: deliveries(status="dead"), timeout=60)
        dead = deliveries(status="dead")[0]
        check("the delivery made 4 attempts (1 + 3 retries) then stopped", dead["attempt_count"] == 4)
        partner.always_fail = False
        client.post(f"/v1/webhook-deliveries/{dead['id']}/retry", headers=headers)
        wait_for("the manual retry", lambda: len(partner.accepted) == 3)
        check("the manual retry was delivered", True)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()
    print("ALL WEBHOOK END-TO-END CHECKS PASSED")


if __name__ == "__main__":
    main()
