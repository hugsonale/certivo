"""Sandbox simulation: a scripted two-participant call with a mid-call confidence drop.

Exercises the whole pipeline with no ML (PRD sandbox requirement). `client` is any
httpx-compatible client (httpx.Client with base_url, or Starlette's TestClient).
"""
from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.attestation import verify_attestation
from app.crypto import SCORE_DOMAIN, public_key_b64u, sign_message
from app.timeutil import now_ms as real_now_ms


def make_signed_packet(private_key: Ed25519PrivateKey, session_id: str, device_id: str,
                       participant: str, seq: int, start_ms: int, end_ms: int,
                       confidence_milli: int, reasons: list[str] | None = None,
                       model_version: str = "sandbox-0") -> dict:
    packet = {
        "v": 1, "participant_reference": participant, "device_id": device_id, "seq": seq,
        "interval_start_ms": start_ms, "interval_end_ms": end_ms,
        "confidence_milli": confidence_milli, "model_version": model_version,
        "explanation": {"reason_codes": reasons or ["sandbox_scripted"],
                        "signal_milli": {"consistency": confidence_milli}},
    }
    signed = dict(packet, session_id=session_id)
    packet["device_signature"] = sign_message(private_key, SCORE_DOMAIN, signed)
    return packet


def run_simulation(client, api_key: str, *, intervals: int = 12, drop_at: int = 6,
                   now_ms: int | None = None) -> dict:
    auth = {"Authorization": f"Bearer {api_key}"}
    now = now_ms if now_ms is not None else real_now_ms()

    people = {}
    for name in ("alice", "bob"):
        key = Ed25519PrivateKey.generate()
        r = client.post("/v1/devices", json={"public_key": public_key_b64u(key)}, headers=auth)
        r.raise_for_status()
        people[name] = (key, r.json()["id"])

    r = client.post("/v1/sessions/continuous", headers=auth, json={
        "use_case": "default_video_call", "participant_count": 2,
        "call_session_reference": "sandbox-call-1"})
    r.raise_for_status()
    session = r.json()
    sdk = {"Authorization": f"Bearer {session['sdk_token']}"}
    path = f"/internal/v1/sessions/continuous/{session['id']}/score-events"

    timeline = []
    base = now - intervals * 1000
    for i in range(intervals):
        start, end = base + i * 1000, base + (i + 1) * 1000
        for name, (key, dev_id) in people.items():
            injected = name == "bob" and i >= drop_at
            conf = 150 if injected else 930
            reasons = ["temporal_discontinuity"] if injected else ["consistent_motion"]
            pkt = make_signed_packet(key, session["id"], dev_id, name, i, start, end, conf, reasons)
            resp = client.post(path, json=pkt, headers=sdk)
            resp.raise_for_status()
            timeline.append((i, name, conf, resp.json()["current_policy_outcome"]))

    end = client.post(f"/v1/sessions/continuous/{session['id']}/end", headers=auth)
    end.raise_for_status()
    result = end.json()
    keys = client.get("/.well-known/certivo-keys").json()["keys"]
    pub = next(k["public_key"] for k in keys if k["key_id"] == result["attestation"]["key_id"])
    return {"session_id": session["id"], "timeline": timeline, "end": result,
            "attestation_verified": verify_attestation(result["attestation"], pub)}
