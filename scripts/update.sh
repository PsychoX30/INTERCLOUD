#!/usr/bin/env bash
#
# Intercloud Portal — in-place update. Runs on the production server as
# either root or the `intercloud` service user.
#
#   sudo -u intercloud bash /opt/intercloud-portal/scripts/update.sh
#
# Also invoked by the admin API `POST /api/portal/admin/system/update`.
#
# Guarantees:
#   1. Always dumps the DB first (auto-backup) to a timestamped file.
#   2. Preserves the two .env files verbatim.
#   3. Installs any new Python + Node deps.
#   4. Rebuilds the frontend production bundle.
#   5. Restarts the backend via supervisor. nginx keeps serving stale
#      /frontend/build for the ~30 sec build window with zero downtime.
#
# Exit code:
#   0 = success, non-zero = failure. On failure NOTHING has been dropped:
#   the backup archive is written before any git/rebuild step.
#
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/intercloud}"
BRANCH="${REPO_BRANCH:-main}"

log() { echo -e "==> $*"; }

mkdir -p "$BACKUP_DIR"
cd "$APP_DIR" || { echo "Missing $APP_DIR"; exit 1; }

STAMP=$(date -u +'%Y%m%dT%H%M%SZ')
ARCHIVE="$BACKUP_DIR/pre-update-$STAMP.archive.gz"

# ---- 1. Snapshot DB first (atomic swap so a full disk can't produce a
# ----    half-written archive that later mongorestore would happily eat) --
log "Snapshotting DB → $ARCHIVE"
source "$APP_DIR/backend/.env" 2>/dev/null || true
MONGO_URL="${MONGO_URL:-mongodb://127.0.0.1:27017}"
DB_NAME="${DB_NAME:-intercloud_portal}"
if ! mongodump --uri "$MONGO_URL" --db "$DB_NAME" --archive="$ARCHIVE.tmp" --gzip; then
    rm -f "$ARCHIVE.tmp"
    echo "!! Backup failed — aborting update"; exit 2
fi
mv -f "$ARCHIVE.tmp" "$ARCHIVE"

# Prune backups older than 30 days so /var doesn't fill up.
find "$BACKUP_DIR" -type f -name 'pre-update-*.archive.gz' -mtime +30 -delete 2>/dev/null || true

# ---- 2. Snapshot HEAD before pull ------------------------------------------
OLD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

# ---- 3. Fetch + fast-forward -----------------------------------------------
# Refuse to run on a dirty tree — silently stashing risks pocketing code that
# hasn't yet been committed (Emergent auto-commit lag, live .env edits, log
# artefacts) and reverting the running system to an older commit. If ops
# genuinely wants to discard local changes, they can `git reset --hard` first.
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "!! Refusing to update: working tree has uncommitted changes."
    echo "!! Run 'git status' to inspect; commit / stash / reset manually first."
    exit 3
fi

# Detect a remote so we don't hard-fail on non-git checkouts.
if ! git remote -v | grep -q .; then
    echo "STATUS=nogit OLD=$OLD_SHA NEW=$OLD_SHA BACKUP=$ARCHIVE"
    echo "!! No git remote configured — nothing to pull."
    exit 4
fi

log "Fetching origin/$BRANCH"
git fetch --all --prune

git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

NEW_SHA=$(git rev-parse HEAD)
if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
    log "Already at $NEW_SHA — nothing to update"
    echo "STATUS=noop OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE"
    exit 0
fi

# ---- 4. Update backend deps ------------------------------------------------
log "Installing Python deps"
if [[ -d "$APP_DIR/backend/.venv" ]]; then
    "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip wheel >/dev/null
    "$APP_DIR/backend/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
else
    python3.12 -m venv "$APP_DIR/backend/.venv"
    "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip wheel
    "$APP_DIR/backend/.venv/bin/pip" install -r "$APP_DIR/backend/requirements.txt"
fi

# ---- 5. Update frontend deps + build ---------------------------------------
log "Installing frontend deps + building production bundle"
cd "$APP_DIR/frontend"
yarn install --frozen-lockfile || yarn install
yarn build

# ---- 6. Restart backend (nginx serves static build automatically) ----------
log "Restarting backend via supervisor"
if command -v supervisorctl >/dev/null 2>&1; then
    supervisorctl restart intercloud-backend || sudo supervisorctl restart intercloud-backend || true
fi

log "Update complete. $OLD_SHA → $NEW_SHA"
echo "STATUS=ok OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE"
