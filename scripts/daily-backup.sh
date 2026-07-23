#!/usr/bin/env bash
#
# Intercloud Portal — daily rolling backup, driven by /etc/cron.d/intercloud-backup.
#
# Produces one gzipped BSON archive per day under $BACKUP_DIR:
#     daily-YYYYMMDD.archive.gz
# and prunes anything older than $RETENTION_DAYS (default 14).
#
# Runs as root (via cron.d). Loads DB credentials from backend/.env so it
# works whether or not MongoDB auth is on.
#
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/intercloud}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

# Source backend .env so MONGO_URL + DB_NAME are populated for auth-mode.
if [[ -f "$APP_DIR/backend/.env" ]]; then
  # shellcheck disable=SC1091
  set -a; . "$APP_DIR/backend/.env"; set +a
fi
MONGO_URL="${MONGO_URL:-mongodb://127.0.0.1:27017}"
DB_NAME="${DB_NAME:-intercloud_portal}"

STAMP=$(date -u +'%Y%m%d')
ARCHIVE="$BACKUP_DIR/daily-$STAMP.archive.gz"

# Atomic swap so a partial dump can't be confused with a valid archive.
if mongodump --uri "$MONGO_URL" --db "$DB_NAME" --archive="$ARCHIVE.tmp" --gzip --quiet; then
    mv -f "$ARCHIVE.tmp" "$ARCHIVE"
    echo "[$(date -u +%FT%TZ)] daily backup OK → $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
else
    rm -f "$ARCHIVE.tmp"
    echo "[$(date -u +%FT%TZ)] daily backup FAILED" >&2
    exit 1
fi

# Rotate — keep last $RETENTION_DAYS
find "$BACKUP_DIR" -type f -name 'daily-*.archive.gz' -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true
