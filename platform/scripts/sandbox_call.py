"""Run a scripted call against a running server.
    python scripts/sandbox_call.py --api-key cvk_... [--base-url http://127.0.0.1:8000]"""
import argparse
import sys

import httpx

sys.path.insert(0, ".")
from app.sandbox import run_simulation  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--api-key", required=True)
p.add_argument("--base-url", default="http://127.0.0.1:8000")
args = p.parse_args()

with httpx.Client(base_url=args.base_url, timeout=10) as client:
    out = run_simulation(client, args.api_key)

print(f"session {out['session_id']}")
print("interval  participant  confidence  outcome")
for i, who, conf, outcome in out["timeline"]:
    print(f"{i:>8}  {who:<11}  {conf:>10}  {outcome}")
for part in out["end"]["attestation"]["payload"]["participants"]:
    print(part)
print("coverage:", out["end"]["coverage_summary"])
print("attestation signature verified:", out["attestation_verified"])
