# Working agreement

This file is the short version of the Certivo Master Build Guide, Part 2. If this file and the guide disagree, stop and fix whichever is wrong.

## 1. Branches

- `main` is the stable branch. `rebuild` is the working trunk until we cut `main` over to it.
- Work on a branch named `feat/<step-id>-short-name`, for example `feat/P0-03-alembic`.
  Other prefixes: `fix/`, `docs/`, `chore/`, `ci/`.
- One pull request per build step, even when working alone, so the checks always run.

## 2. Commit messages (Conventional Commits)

The first line must look like `type(scope): summary`.

| Type | Use for |
|---|---|
| `feat` | a new capability |
| `fix` | a bug fix |
| `docs` | documentation only |
| `chore` | tooling, dependencies, housekeeping |
| `test` | tests only |
| `refactor` | code change with no behaviour change |
| `perf` | speed or resource improvements |
| `ci` | workflow changes |
| `build` | build system changes |
| `revert` | undoing an earlier commit |

Examples: `feat(platform): add webhook worker`, `docs: add ADR for signing algorithm`.
Put the build step ID (for example `P0-07`) in the body of the message.
The pull request title follows the same format. A check enforces it.

Turn on the local check once per clone:

```bash
git config core.hooksPath .githooks
```

## 3. Pull request flow

1. Create the branch, make the change, run the tests locally.
2. Open a pull request. The template appears; fill it in honestly.
3. Wait for every check to go green: platform-ci (including the Postgres and Docker checks), governance, security-scan.
4. Merge with **Squash and merge** so each step is one clean commit.
5. Update the tracker row and add a line to the progress log.

## 4. Decisions and progress

- Every significant decision gets an ADR in `docs/adr/` (copy `0000-template.md`).
- Every working session adds an entry to the month's file in `docs/progress/`.
- Every public claim about accuracy, speed, overhead or privacy is listed in the claims register in the Master Build Guide with its evidence. No evidence, no claim.

## 5. Database changes

Every schema change is a migration. If you change `platform/app/models.py`, create a migration in the
same pull request (`alembic revision --autogenerate --rev-id 000N -m "what"`), read it, and run
`alembic check`. CI fails if the models and the migrations disagree. Never edit a migration that has
already been applied anywhere except your own computer. Full instructions: `platform/README.md`, section 2.

## 6. Definition of done

1. The behaviour works and is covered by automated tests (or, for non-code work, a reviewed written artifact exists).
2. It passes the checklist in the pull request template.
3. The relevant spec or document is updated in the same pull request.
4. The tracker is updated with evidence (PR link, test output, report path).
5. Nothing in the repo contains secrets, personal data or raw media.

## 7. Secrets: the one rule that matters most

Never commit a password, API key, signing key or `.env` file. If one is ever committed by mistake:

1. **Rotate it first** (change it at the source so the old value is useless).
2. Then remove it from the code.
3. Tell the team. History cleanup comes after, and does not replace rotation.

## 8. Running the platform locally

See `platform/README.md`.
