#!/usr/bin/env bash
# Certivo repo cleanup + rebuild branch setup.
# Run from the repo root, on branch main, with a clean working tree.
# It NEVER pushes. You push manually at the end (see printed next steps).
set -euo pipefail

BASE_BRANCH="main"
NEW_BRANCH="rebuild"
LEGACY_TAG="legacy-liveness-v0"

# ---- safety checks -------------------------------------------------------
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "Not inside a git repo."; exit 1; }
cd "$(git rev-parse --show-toplevel)"
[ "$(git branch --show-current)" = "$BASE_BRANCH" ] || { echo "Switch to $BASE_BRANCH first."; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Working tree not clean. Commit or stash first."; exit 1; }
git rev-parse -q --verify "refs/tags/$LEGACY_TAG" >/dev/null && { echo "Tag $LEGACY_TAG already exists."; exit 1; }
git rev-parse -q --verify "refs/heads/$NEW_BRANCH" >/dev/null && { echo "Branch $NEW_BRANCH already exists."; exit 1; }

# ---- phase 1: make main safe (stop tracking secrets / junk) --------------
echo "== Phase 1: stop tracking secrets and junk on $BASE_BRANCH"
git rm --cached -q -f .env 2>/dev/null || true
git rm -r --cached -q frontend/node_modules 2>/dev/null || true
git rm --cached -q -f -- '*.backup' '*.backup_*' '*.db.backup*' backups/* .coverage 2>/dev/null || true

cat >> .gitignore <<'EOF'

# --- added by rebuild_setup.sh ---
.env
.env.*
!.env.example
node_modules/
*.backup
*.backup_*
.coverage
__pycache__/
*.db
backups/
EOF
git add .gitignore
git commit -q -m "chore: stop tracking .env, node_modules and backup files"

# ---- phase 2: freeze the old prototype under a tag -----------------------
echo "== Phase 2: tag $LEGACY_TAG"
git tag -a "$LEGACY_TAG" -m "Original Flask/FastAPI challenge-based liveness prototype, frozen before the rebuild"

# ---- phase 3: rebuild branch ---------------------------------------------
echo "== Phase 3: create $NEW_BRANCH"
git checkout -q -b "$NEW_BRANCH"

# Things worth porting from. Everything else is deleted from this branch
# (it all stays retrievable from the tag).
KEEP=(
  services/shared
  services/legal
  services/data_privacy
  services/security
  admin
  api/openapi.yaml
  red_team
  infrastructure
  docs
  tests
  config/data_classifications.py
  docker-compose.yml
  requirements.txt
  ...github
)

for p in "${KEEP[@]}"; do
  if [ -e "$p" ]; then
    dest="legacy/$p"
    [ "$p" = "...github" ] && dest="legacy/ci"
    mkdir -p "$(dirname "$dest")"
    git mv "$p" "$dest"
  fi
done

# Remove every tracked file that is not under legacy/ and not on the root allow-list.
git ls-files -z \
  | grep -zv '^legacy/' \
  | grep -zvE '^(\.gitignore|\.gitleaks\.toml)$' \
  | xargs -0 -r git rm -q -f

# New layout
mkdir -p platform sdk-web demo-call docs/spec
cat > README.md <<'EOF'
# Certivo

Trust infrastructure for live human interaction: an embeddable SDK that gives every
participant on a live call a continuously updated, signed trust signal about the others.

## Layout

- `platform/`   FastAPI backend (sessions, score events, attestation, trusted devices)
- `sdk-web/`    Web SDK (on-device inference, signed score packets)
- `demo-call/`  Two-person WebRTC demo app used to test and measure the SDK
- `docs/spec/`  The 18-document specification suite
- `legacy/`     Frozen reference code from the original prototype (tag `legacy-liveness-v0`).
                Port from here deliberately; delete when nothing is left worth porting.
EOF
cat > legacy/README.md <<'EOF'
Reference only. Do not import from here in new code. Move a module out of `legacy/`
(and adapt it) when you port it. Full original tree: `git show legacy-liveness-v0:<path>`.
EOF
for d in platform sdk-web demo-call docs/spec; do touch "$d/.gitkeep"; done

git add -A
git commit -q -m "chore: start rebuild - freeze prototype under legacy/, add new layout"

echo
echo "Done. Current branch: $(git branch --show-current)"
echo
echo "Next steps (manual):"
echo "  1. Copy the 18 spec .docx files into docs/spec/ and commit them."
echo "  2. git push origin $BASE_BRANCH"
echo "  3. git push origin $LEGACY_TAG"
echo "  4. git push -u origin $NEW_BRANCH"
