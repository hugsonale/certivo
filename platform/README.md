# Certivo platform (Phase 0)

FastAPI backend for continuous sessions: signed score packets in, policy outcomes and a signed
session-length attestation out. Read `docs/spec/BUILD_SPEC_0.md` first.

## 1. Run it (Windows, Git Bash)

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

In dev (`CERTIVO_ENV=dev`) the app and `create_partner.py` apply database migrations for you.

**If you ran an earlier version of this project:** delete the old dev database once with
`rm certivo_dev.db`, then run `create_partner.py` again. The old file was built without migrations,
so the new migration system cannot adopt it. It only held sandbox data.

## 2. Database migrations (the rule: every schema change is a migration)

The database structure is defined by the files in `migrations/versions/`, never by code that
creates tables directly. Run these from the `platform/` folder with the virtual environment active.

| Task | Command |
|---|---|
| Apply all migrations | `alembic upgrade head` |
| Show which migration the database is at | `alembic current` |
| Check that `app/models.py` and the migrations agree | `alembic check` |
| Draft a new migration after changing `app/models.py` | `alembic revision --autogenerate --rev-id 0002 -m "what changed"` |
| Undo the last migration (dev only) | `alembic downgrade -1` |

**When you change `app/models.py`:**

1. Run `alembic revision --autogenerate --rev-id 0002 -m "short description"`. Use the next number.
2. **Open the new file in `migrations/versions/` and read it.** Autogenerate can miss things (a renamed
   column looks like "drop one, add one", which would destroy data).
3. Run `alembic upgrade head`, then `alembic check` (it should say "No new upgrade operations detected").
4. Run `pytest`. Commit the model change and the migration **in the same pull request**.

Never edit a migration that has already been applied anywhere except your own computer. Add a new one.

**Dev versus everything else.** With `CERTIVO_ENV=dev` the app migrates automatically at startup. With
any other value (`staging`, `prod`, and so on) the app never changes the database: you run
`alembic upgrade head` first, and the app refuses to start if the database is not up to date.

## 3. API keys and abuse protection

Every `/v1/` call needs an API key, and each key only works for the things its **scopes** allow. In
Git Bash (replace the key with yours from `create_partner.py`; the server must be running):

```bash
export KEY=cvk_YOUR_KEY_HERE
BASE=http://127.0.0.1:8000

# 1. make a read-only key. The full key appears ONCE in the reply: copy it now
curl -s -X POST $BASE/v1/api-keys -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" -d '{"name":"read only","scopes":["sessions:read"]}'

# 2. list your keys (the secrets are never shown again)
curl -s $BASE/v1/api-keys -H "Authorization: Bearer $KEY"

# 3. try the read-only key on something it must not do: you should get 403 forbidden_scope
export READ_ONLY_KEY=PASTE_THE_NEW_KEY_FROM_STEP_1_HERE
curl -s -X POST $BASE/v1/sessions/continuous -H "Authorization: Bearer $READ_ONLY_KEY" \
  -H "Content-Type: application/json" -d '{"use_case":"default_video_call"}'

# 4. revoke it (use the id that starts with key_). It stops working at once
curl -s -X DELETE $BASE/v1/api-keys/key_ID_HERE -H "Authorization: Bearer $KEY" -i
```

Available scopes: `sessions:write`, `sessions:read`, `devices:write`, `devices:read`, `policies:write`,
`policies:read`, `webhooks:write`, `webhooks:read`, `consents:write`, `consents:read`, `audit:read`,
`analytics:read`, `keys:admin`. A key can never hand out a scope it does not hold itself.

**Settings.** Put any of these in `.env` (each starts with `CERTIVO_`). **Every number is a placeholder**
to be replaced with values from measured traffic, not a recommendation.

| Setting | Default | What it does |
|---|---|---|
| `SDK_TOKEN_TTL_SECONDS` | 21600 | An SDK token stops working this long after the session starts |
| `RATE_LIMIT_KEY_PER_MINUTE` | 600 | Requests per API key per minute |
| `RATE_LIMIT_SESSION_PER_MINUTE` | 1800 | Requests per SDK session per minute |
| `RATE_LIMIT_AUTH_FAILURES_PER_MINUTE` | 20 | Failed sign-ins per network address (and per key prefix) per minute |
| `TRUSTED_PROXY_HOPS` | 0 | How many reverse proxies are in front of the service. Leave 0 unless you are sure |
| `MAX_BODY_BYTES` | 65536 | Larger request bodies get 413 |
| `BODY_READ_TIMEOUT_S` | 10 | A body that stalls this long gets 408 |
| `DB_STATEMENT_TIMEOUT_MS` | 5000 | No database statement may run longer |
| `MAX_API_KEYS_PER_PARTNER` | 50 | Active keys per partner |
| `CORS_ALLOWED_ORIGINS` | empty | Browser origins allowed to call the SDK endpoints, comma separated, exact `https://` origins |
| `ENABLE_DOCS` | on in dev only | The `/docs` page |

Rate limits are counted inside one server process today (see `docs/adr/0012`), so they are weaker than they
look when several processes run.

## 4. Running on Postgres

SQLite is what you use by default. Production uses Postgres, and CI runs every test on both.

**Option A (nothing to install): let GitHub do it.** Open a pull request. The check named
"Tests and migration check on Postgres" runs the whole suite on a real Postgres.

**Option B: run the whole stack with Docker.** Needs Docker Desktop.

```bash
cd platform
python scripts/gen_signing_key.py       # put the output in .env as CERTIVO_ATTESTATION_SIGNING_KEY=
docker compose up --build               # starts Postgres and the API, runs the migrations
```

Then open http://127.0.0.1:8000/docs. In a second terminal:

```bash
docker compose exec api python scripts/create_partner.py "Docker Partner"
docker compose exec api python scripts/sandbox_call.py --api-key cvk_...
docker compose down        # stop (add -v to also delete the database volume)
```

**Option C: run the tests against your own Postgres.** Create an empty database, then:

```bash
export CERTIVO_TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/certivo_test"
pytest
```

## 5. Layout

| Path | What |
|---|---|
| `app/crypto.py` | canonical JSON profile, Ed25519 sign/verify (the cross-language contract) |
| `app/policy.py` | per-interval accept / fallback / reject (placeholder thresholds) |
| `app/services/sessions.py` | start, ingest, pause/resume, end + attestation, status |
| `app/attestation.py` | platform signer, attestation verification helper |
| `app/security.py` | API keys, scopes, SDK tokens, rate-limit and failed-login checks |
| `app/hardening.py` | request ID, security headers, body size and slow-body limits, CORS |
| `app/ratelimit.py`, `app/scopes.py` | the rate limiter and the list of scopes |
| `app/db.py` | database engine plus the migration helpers |
| `alembic.ini`, `migrations/` | the database schema, as migrations |
| `app/sandbox.py` | scripted call used by tests and `scripts/sandbox_call.py` |
| `tests/` | 128 tests; run on SQLite and Postgres |

## 6. Rules we hold ourselves to

- `.env`, API keys, signing keys and `*.db` never get committed (`.gitignore` covers them).
- Any change to the packet format must update `docs/spec/test-vectors/` via
  `python scripts/gen_test_vectors.py`; a test fails if they drift.
- Any change to `app/models.py` needs a migration in the same pull request; a test and CI fail if not.
