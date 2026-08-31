#!/usr/bin/env bash
# Redeploy QBCals on the EC2 server - automates docs/DEPLOY_EC2.md's
# "Deploying updates later" steps. Run from anywhere; cd's to ~/SBIQ itself.
#
# Usage: ./redeploy.sh
set -euo pipefail

REPO_DIR="$HOME/SBIQ"
SERVICES="qbcals-api qbcals-worker-enrichment qbcals-worker-matching"

log() { printf '\n>> %s\n' "$1"; }

cd "$REPO_DIR"

# Bail out early on uncommitted local changes rather than letting `git pull`
# fail or silently merge over something someone was mid-edit on directly on
# the server - that's a real (if rare) way to lose work on a box people
# sometimes hotfix on directly.
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: $REPO_DIR has uncommitted changes - resolve or stash before redeploying:" >&2
    git status --short >&2
    exit 1
fi

BEFORE_SHA="$(git rev-parse HEAD)"
log "Pulling latest changes..."
git pull
AFTER_SHA="$(git rev-parse HEAD)"

if [ "$BEFORE_SHA" = "$AFTER_SHA" ]; then
    log "Already up to date (HEAD unchanged) - nothing to redeploy."
    exit 0
fi

CHANGED_FILES="$(git diff --name-only "$BEFORE_SHA" "$AFTER_SHA")"

cd backend
source myenv/bin/activate

if echo "$CHANGED_FILES" | grep -q '^backend/requirements\.txt$'; then
    log "requirements.txt changed - installing dependencies..."
    pip install -r requirements.txt
else
    log "requirements.txt unchanged - skipping pip install."
fi

# Checked against alembic's own current-vs-head state, not just whether
# alembic/versions/ files changed in the pull - more reliable (e.g. also
# catches a migration that was only just added to a branch merged in, or a
# server that fell behind before this script existed) and "alembic upgrade
# head" is a safe no-op when already current, so there's no real cost to
# checking this way instead of git-diffing file paths.
CURRENT_REV="$(alembic current 2>/dev/null | awk '{print $1}')"
HEAD_REV="$(alembic heads 2>/dev/null | awk '{print $1}')"
if [ "$CURRENT_REV" != "$HEAD_REV" ]; then
    log "Pending migrations ($CURRENT_REV -> $HEAD_REV) - running alembic upgrade head..."
    alembic upgrade head
else
    log "Database already at head revision ($CURRENT_REV) - skipping migrations."
fi

log "Restarting services: $SERVICES"
sudo systemctl restart $SERVICES

log "Waiting for the API to come back up..."
for _ in $(seq 1 15); do
    if curl -sf http://localhost:8000/health > /dev/null; then
        log "Redeploy complete - API is healthy."
        sudo systemctl status --no-pager $SERVICES
        exit 0
    fi
    sleep 2
done

echo "ERROR: API did not become healthy within 30s after restart - check logs:" >&2
echo "  journalctl -u qbcals-api -n 50 --no-pager" >&2
exit 1
