#!/usr/bin/env bash
#
# Intercloud Portal — backup freshness watchdog.
#
# The failure mode this exists for: backups that "run" but silently stop
# producing usable output. cron logs to a file nobody reads, MAILTO is empty,
# and a 14-day rolling window means the bad state is invisible until restore
# day — which is exactly when it matters.
#
# It checks AGE, not exit codes, and it exercises the archive rather than
# trusting that a file with the right name exists.
#
# Exit 0 = healthy, exit 1 = problem (cron mails/logs it).
#
set -uo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/intercloud}"
BIZ_DIR="$BACKUP_DIR/business"
MAX_BIZ_AGE_MIN="${MAX_BIZ_AGE_MIN:-90}"      # hourly job -> 90 min tolerance
# The age this compares is (now - midnight of the UTC date in the filename),
# NOT time since the archive was written. daily-backup.sh runs at 03:15 WIB
# (20:15 UTC) and names the file with the UTC date at that moment, so the
# newest archive is 20.25 h of age the instant it is written and grows to
# 44.25 h just before the next run 24 h later. A 30 h limit therefore fired
# every day from 06 UTC to 21 UTC (13 h out of 24, ~31-34 h reported) on a
# perfectly healthy backup line. 48 h = 44.25 h worst case + 3.75 h slack for
# a late run. Do not lower this without changing the filename scheme.
MAX_FULL_AGE_HOURS="${MAX_FULL_AGE_HOURS:-48}"
MIN_BIZ_BYTES="${MIN_BIZ_BYTES:-1000000}"
LOG_TAG="[$(date -u +%FT%TZ)]"

problems=()

# --- 1. hourly business snapshot must exist and be recent -------------------
LATEST_BIZ=$(ls -1t "$BIZ_DIR"/biz-*.archive.gz 2>/dev/null | head -1)
if [[ -z "$LATEST_BIZ" ]]; then
  problems+=("no business snapshot found in $BIZ_DIR")
else
  age_min=$(( ( $(date +%s) - $(stat -c %Y "$LATEST_BIZ") ) / 60 ))
  size=$(stat -c %s "$LATEST_BIZ")
  [[ "$age_min" -gt "$MAX_BIZ_AGE_MIN" ]] \
    && problems+=("business snapshot is ${age_min} min old (limit ${MAX_BIZ_AGE_MIN})")
  [[ "$size" -lt "$MIN_BIZ_BYTES" ]] \
    && problems+=("business snapshot is only ${size} bytes (floor ${MIN_BIZ_BYTES})")
  # The file must actually decompress. A truncated gzip passes an existence
  # check and fails on restore day.
  gzip -t "$LATEST_BIZ" 2>/dev/null || problems+=("business snapshot is corrupt: $(basename "$LATEST_BIZ")")
fi

# --- 2. daily full archive must not be stale -------------------------------
LATEST_FULL=$(ls -1t "$BACKUP_DIR"/daily-*.archive.gz 2>/dev/null | head -1)
if [[ -z "$LATEST_FULL" ]]; then
  problems+=("no full daily archive found in $BACKUP_DIR")
else
  # Age is taken from the date embedded in the filename, NOT the mtime. mtime is
  # metadata that a copy, rsync or touch can move; daily-YYYYMMDD encodes the age
  # of the DATA, which is what decides how much is lost on restore. Judging by
  # mtime also mis-picks "newest" entirely when a touch reorders the directory.
  full_date=$(basename "$LATEST_FULL" | sed -E 's/^daily-([0-9]{8})\.archive\.gz$/\1/')
  if [[ "$full_date" =~ ^[0-9]{8}$ ]]; then
    full_epoch=$(date -u -d "${full_date:0:4}-${full_date:4:2}-${full_date:6:2}" +%s 2>/dev/null)
    if [[ -n "$full_epoch" ]]; then
      age_h=$(( ( $(date +%s) - full_epoch ) / 3600 ))
      [[ "$age_h" -gt "$MAX_FULL_AGE_HOURS" ]] \
        && problems+=("newest full archive daily-${full_date} is ${age_h} h of data old (limit ${MAX_FULL_AGE_HOURS})")
    fi
  fi
fi

# --- 3. disk must still hold tomorrow's backup -----------------------------
use_pct=$(df --output=pcent /var/backups 2>/dev/null | tail -1 | tr -dc '0-9')
[[ -n "$use_pct" && "$use_pct" -ge 90 ]] \
  && problems+=("/var/backups filesystem is ${use_pct}% full")

# --- report ----------------------------------------------------------------
if (( ${#problems[@]} == 0 )); then
  echo "$LOG_TAG backup health OK (business: $(basename "${LATEST_BIZ:-none}"), full: $(basename "${LATEST_FULL:-none}"))"
  exit 0
fi

echo "$LOG_TAG BACKUP HEALTH PROBLEM:" >&2
for p in "${problems[@]}"; do echo "  - $p" >&2; done

# Mirror into the app log so it shows up next to everything else.
echo "$(date -u +%FT%TZ) BACKUP HEALTH PROBLEM: ${problems[*]}" >> /var/log/intercloud-backup-alerts.log 2>/dev/null || true
exit 1
