# Certivo platform (Phase 0)

FastAPI backend for continuous sessions: signed score packets in, policy outcomes and a signed
session-length attestation out. Read `docs/spec/BUILD_SPEC_0.md` first.

## Run it (Windows, Git Bash)

```bash
cd platform
python --version                      # needs 3.10+
python -m venv .venv
source .venv/Scripts/activate         # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                                # all tests should pass
ruff check .

cp .env.example .env
python scripts/gen_signing_key.py     # paste the output into CERTIVO_ATTESTATION_SIGNING_KEY in .env
python scripts/create_partner.py "My Partner"     # prints an API key ONCE: save it

python -m uvicorn app.main:create_app --factory --reload     # http://127.0.0.1:8000/docs

# in a second terminal (venv active), run a scripted two-person call with a mid-call drop:
python scripts/sandbox_call.py --api-key cvk_...
```

## Layout

| Path | What |
|---|---|
| `app/crypto.py` | canonical JSON profile, Ed25519 sign/verify (the cross-language contract) |
| `app/policy.py` | per-interval accept / fallback / reject (placeholder thresholds) |
| `app/services/sessions.py` | start, ingest, pause/resume, end + attestation, status |
| `app/attestation.py` | platform signer, attestation verification helper |
| `app/sandbox.py` | scripted call used by tests and `scripts/sandbox_call.py` |
| `tests/` | 35 tests, including the shared test vector |

## Rules we hold ourselves to

- `.env`, API keys, signing keys and `*.db` never get committed (`.gitignore` covers them).
- Any change to the packet format must update `docs/spec/test-vectors/` via
  `python scripts/gen_test_vectors.py`; a test fails if they drift.
- `docker-compose.yml` and Postgres have **not been tested yet** (SQLite is what the tests use).
