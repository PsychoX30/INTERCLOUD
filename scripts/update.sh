#!/usr/bin/env bash
#
# Intercloud Portal — in-place update. Runs on the production server as
# either root or the `intercloud` service user.
#
#   sudo -u intercloud bash /opt/intercloud-portal/scripts/update.sh
#
# Also invoked (detached) by the admin API `POST /api/portal/admin/system/update`;
# progress can be polled via `GET /api/portal/admin/system/update/status`.
#
# Guarantees:
#   1. Always dumps the DB first (auto-backup) to a timestamped file.
#   2. Preserves the two .env files verbatim.
#   3. Installs any new Python + Node deps (Emergent pod-only packages such as
#      emergentintegrations/litellm are filtered out - they are not on PyPI
#      and are never imported by this app).
#   4. Rebuilds the frontend production bundle.
#   5. Restarts the backend via supervisor. nginx keeps serving stale
#      /frontend/build for the ~30 sec build window with zero downtime.
#
# Self-update safety: phase 1 (backup + git pull) re-execs the FRESHLY PULLED
# copy of this script for phase 2 (deps/build/restart), so fixes to the update
# process itself always take effect in the same run.
#
# Exit code:
#   0 = success/noop, 2 = backup failed, 3 = dirty tree, 4 = no git remote.
#   5 = build/deps complete but the Supervisor restart did not happen. When the
#       deploy user holds the narrow rule in
#       /etc/sudoers.d/supervisor-restart-backend (only
#       `supervisorctl restart intercloud-backend`), the restart is performed
#       with `sudo -n` and this code is not reached. Exit 5 means the rule is
#       absent or the restart genuinely failed: the source is deployed but the
#       backend still runs the previous process, so restart it as root/support
#       before declaring the deploy complete. `ALLOW_SUDO_RESTART=0` forces
#       this path deliberately.
#   6 = deploy key missing (see DEPLOY_KEY_DIR).
#   7 = artifact ownership could not be corrected; the build was NOT attempted
#       and the live site was left untouched.
#   On failure NOTHING has been dropped: the backup archive is written before
#   any git/rebuild step.
#
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# Pastikan artefak build yang bisa ditulis service user SEBELUM build dimulai.
# 2026-11-16: frontend/build (dan node_modules) tertinggal milik user lain dari
# build manual yang dijalankan sebagai user berbeda. `npm ci` meneruskannya,
# sehingga craco menjalankan rmdir pada build/static/css milik user lain,
# kena EACCES lalu mati - tepat SETELAH react-scripts mengosongkan build/.
# Situs down sampai ada build berikutnya yang berhasil.
ensure_euid_ownership() {
    local p
    for p in "$APP_DIR/frontend/build" "$APP_DIR/frontend/node_modules" "$APP_DIR/backend/.version.json"; do
        [[ -e "$p" || -L "$p" ]] || continue
        if [[ "$(stat -c '%u' "$p" 2>/dev/null || echo 0)" != "${EUID}" ]]; then
            log "Fixing ownership of $p ($(stat -c '%U:%G' "$p" 2>/dev/null) -> $(id -un))"
            chown -R "${EUID}:$(id -g)" "$p" 2>/dev/null || {
                echo "!! cannot chown $p; re-run as root (sudo -u intercloud is not enough)" >&2
                return 1
            }
        fi
    done
    # Sisa direktori staging dari build yang terinterupsi.
    find "$APP_DIR/frontend" -maxdepth 1 -name 'build.stage.*' -user "$(id -u)" \
        -exec rm -rf {} + 2>/dev/null || true
    return 0
}
BACKUP_DIR="${BACKUP_DIR:-/var/backups/intercloud}"
BRANCH="${REPO_BRANCH:-main}"
# Where the GitHub deploy key actually lives. Deliberately OUTSIDE APP_DIR: the
# service user's passwd home is APP_DIR itself, so ssh looks for ~/.ssh there,
# but anything under APP_DIR is disposable git working-tree space.
DEPLOY_KEY_DIR="${DEPLOY_KEY_DIR:-/var/lib/intercloud/.ssh}"

log() { echo -e "==> $*"; }

install_python_deps() {
    # Filter paket internal pod Emergent yang tidak tersedia di PyPI dan tidak
    # pernah di-import aplikasi (emergentintegrations, litellm wheel privat).
    local REQ_PROD="/tmp/requirements.prod.txt"
    grep -vE '^(emergentintegrations|litellm)\b|customer-assets\.emergentagent\.com' \
        "$APP_DIR/backend/requirements.txt" > "$REQ_PROD"
    if [[ ! -d "$APP_DIR/backend/.venv" ]]; then
        python3.12 -m venv "$APP_DIR/backend/.venv"
    fi
    "$APP_DIR/backend/.venv/bin/pip" install --upgrade pip wheel >/dev/null
    "$APP_DIR/backend/.venv/bin/pip" install -r "$REQ_PROD"
}

post_pull() {
    # ---- Phase 2: runs on the NEW checkout (after re-exec) ------------------
    cd "$APP_DIR"
    local OLD_SHA="${UPDATE_OLD_SHA:-unknown}"
    local ARCHIVE="${UPDATE_BACKUP:-none}"
    local NEW_SHA
    NEW_SHA=$(git rev-parse HEAD)

    log "Installing Python deps"
    install_python_deps

    log "Fixing artifact ownership + building production bundle"
    # Ownership first: kalau build/ atau node_modules dipegang user lain, build
    # berikutnya mati di tengah jalan. Lihat komentar ensure_euid_ownership().
    if ! ensure_euid_ownership; then
        echo "!! ownership artefak build tidak bisa diperbaiki — build dibatalkan," \
             "situs TIDAK disentuh" >&2
        echo "STATUS=ownership-failed OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE" >&2
        return 7
    fi
    # build_frontend.sh membekukan VERSION ke frontend/src/version.json dan
    # backend/.version.json SEBELUM build, membangun ke direktori staging, lalu
    # memverifikasi index.html benar-benar menunjuk bundle yang ada di disk
    # sebelum menukarnya secara atomik ke build/. Build yang gagal tidak
    # menyentuh build/ yang sedang dilayani nginx.
    bash "$APP_DIR/scripts/build_frontend.sh"

    log "Restarting backend via supervisor"
    if ! command -v supervisorctl >/dev/null 2>&1; then
        echo "!! supervisorctl not found — backend was not restarted" >&2
        echo "STATUS=restart-required OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE" >&2
        return 5
    fi

    # The production service user cannot reach the root-owned Supervisor socket.
    # `sudo -n` only: never prompt for a password inside an unattended deploy -
    # a prompt with no tty would hang or fail after the code is already live,
    # leaving the old backend process serving the new tree.
    # The narrow rule lives in /etc/sudoers.d/supervisor-restart-backend and
    # grants exactly this one command, nothing else.
    if [[ "${EUID}" -eq 0 ]]; then
        if ! supervisorctl restart intercloud-backend; then
            echo "!! Supervisor restart failed — backend may still serve the old code" >&2
            echo "STATUS=restart-required OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE" >&2
            return 5
        fi
    elif [[ "${ALLOW_SUDO_RESTART:-1}" == "1" ]] \
         && sudo -n /usr/bin/supervisorctl restart intercloud-backend 2>/dev/null; then
        log "Backend restarted via narrow sudoers rule"
    else
        echo "!! Cannot restart Supervisor as $(id -un): root-owned Supervisor socket" >&2
        echo "!! Restart intercloud-backend as root/support before declaring deploy complete" >&2
        echo "STATUS=restart-required OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE" >&2
        return 5
    fi

    # ---- Patch nginx for WebSocket (noVNC VM console) - idempotent ----------
    local NGINX_SITE
    NGINX_SITE=$(grep -rl "proxy_pass http://127.0.0.1:8001" /etc/nginx/sites-enabled/ 2>/dev/null | head -1 || true)
    if [[ -n "$NGINX_SITE" ]] && ! grep -q "connection_upgrade" "$NGINX_SITE"; then
        log "Patching nginx ($NGINX_SITE) for WebSocket console support"
        sed -i '0,/^server {/s//map $http_upgrade $connection_upgrade {\n    default upgrade;\n    '"''"'      close;\n}\n\nserver {/' "$NGINX_SITE"
        sed -i '/location \/api\/ {/,/}/{s|proxy_read_timeout 600s;|proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection $connection_upgrade;\n        proxy_read_timeout 600s;|}' "$NGINX_SITE"
        if nginx -t >/dev/null 2>&1; then
            systemctl reload nginx || sudo systemctl reload nginx || true
            log "nginx patched + reloaded (WebSocket console enabled)"
        else
            log "WARNING: nginx -t failed after patch — review $NGINX_SITE manually"
        fi
    fi

    log "Update complete. $OLD_SHA → $NEW_SHA"
    echo "STATUS=ok OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE"
}

main() {
    if [[ "${UPDATE_PHASE:-}" == "post-pull" ]]; then
        post_pull
        exit 0
    fi

    mkdir -p "$BACKUP_DIR"
    cd "$APP_DIR" || { echo "Missing $APP_DIR"; exit 1; }

    local STAMP ARCHIVE
    STAMP=$(date -u +'%Y%m%dT%H%M%SZ')
    ARCHIVE="$BACKUP_DIR/pre-update-$STAMP.archive.gz"
    # ---- 1. Snapshot DB first (atomic swap so a full disk cannot produce a
    # ----    half-written archive that later mongorestore would happily eat) --
    # To restore: mongorestore --uri "$MONGO_URL" --db "$DB_NAME" --archive="$BACKUP_FILE" --gzip --drop
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

    # ---- 2. Snapshot HEAD before pull ---------------------------------------
    local OLD_SHA
    OLD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "unknown")

    # ---- 3. Fetch + fast-forward --------------------------------------------
    # Refuse to run on a dirty tree — silently stashing risks pocketing code
    # that hasn't yet been committed and reverting the running system.
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "!! Refusing to update: working tree has uncommitted changes."
        echo "!! Run 'git status' to inspect; commit / stash / reset manually first."
        exit 3
    fi

    if ! git remote -v | grep -q .; then
        echo "STATUS=nogit OLD=$OLD_SHA NEW=$OLD_SHA BACKUP=$ARCHIVE"
        echo "!! No git remote configured — nothing to pull."
        exit 4
    fi

    log "Fetching origin/$BRANCH"
    # Deploy key lives at /var/lib/intercloud/.ssh. It is reachable only through
    # the ~/.ssh symlink in this worktree, because ssh reads the config from the
    # passwd home (/opt/intercloud-portal) and NOT from $HOME.
    #
    # Defensive re-link. `git clean -fdx` deletes ignored files by design, so
    # .gitignore alone cannot protect the symlink; if it goes, every fetch dies
    # with "Permission denied (publickey)" and the deploy looks like an SSH
    # breakage rather than a missing link.
    restore_deploy_key_link() {
        [[ -f "$APP_DIR/.ssh/config" ]] && return 0
        [[ -d "$DEPLOY_KEY_DIR" ]] || return 1
        log "Restoring .ssh symlink -> $DEPLOY_KEY_DIR"
        rm -rf "$APP_DIR/.ssh"
        ln -s "$DEPLOY_KEY_DIR" "$APP_DIR/.ssh"
    }
    if ! restore_deploy_key_link; then
        echo "!! Deploy key missing: $DEPLOY_KEY_DIR not found."
        echo "!! Restore it from /var/backups/intercloud-ssh-*/ before retrying."
        exit 6
    fi
    git fetch --all --prune

    git checkout "$BRANCH"
    git pull --ff-only origin "$BRANCH"

    local NEW_SHA
    NEW_SHA=$(git rev-parse HEAD)
    if [[ "$OLD_SHA" == "$NEW_SHA" ]]; then
        log "Already at $NEW_SHA — nothing to update"
        echo "STATUS=noop OLD=$OLD_SHA NEW=$NEW_SHA BACKUP=$ARCHIVE"
        exit 0
    fi

    # ---- 4. Re-exec the freshly pulled script for deps/build/restart --------
    log "Code updated $OLD_SHA → $NEW_SHA; continuing with the new update.sh"
    UPDATE_PHASE=post-pull UPDATE_OLD_SHA="$OLD_SHA" UPDATE_BACKUP="$ARCHIVE" \
        exec /bin/bash "$APP_DIR/scripts/update.sh"
}

main "$@"
