#!/usr/bin/env bash
#
# Intercloud Portal — hourly BUSINESS-ONLY backup.
#
# Why separate from daily-backup.sh:
#   The full DB is ~3.8 GB but ~99% of it is loss-tolerant telemetry
#   (ddos_samples 2.8 GB, cve_entries 0.9 GB, monitoring/flow tables). The data
#   a restore actually needs — users, invoices, services, tickets, crm, orders,
#   transactions — is a few MB. Backing THAT up hourly costs almost nothing and
#   shrinks worst-case data loss from 24 h to 1 h.
#
# Exclusion is derived from LIVE collection sizes, not a hardcoded list, so new
# telemetry is skipped automatically once it grows past $BIG_MB, and a new
# business collection is captured from its very first insert.
#
# THREE TRAPS THIS SCRIPT IS BUILT TO SURVIVE (all hit during development):
#   1. mongodump filters with --excludeCollection. --nsInclude is a
#      mongorestore-only flag; passing it to mongodump dies with
#      "unknown option `nsInclude`".
#   2. The namespace is stored as a BSON field  "collection" : "users", NOT as
#      the dotted string "db.users", so matching the dotted name finds nothing.
#   3. `gzip -dc | grep -q` is binary-hostile: NUL bytes act as line breaks and
#      -q exits at first match, so it rejects perfectly good archives.
#
set -uo pipefail   # deliberately NOT -e: every failure is handled explicitly so
                   # a broken step can never be mistaken for a clean exit.

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/intercloud/business}"
RETENTION_HOURS="${RETENTION_HOURS:-48}"
BIG_MB="${BIG_MB:-32}"
MIN_COLLECTIONS="${MIN_COLLECTIONS:-10}"
MIN_BYTES="${MIN_BYTES:-100000}"

if [[ -f "$APP_DIR/backend/.env" ]]; then
  set -a; . "$APP_DIR/backend/.env"; set +a
fi
MONGO_URL="${MONGO_URL:-mongodb://127.0.0.1:27017}"
DB_NAME="${DB_NAME:-intercloud_portal}"

mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +'%Y%m%dT%H%M%SZ')
ARCHIVE="$BACKUP_DIR/biz-$STAMP.archive.gz"
LOG_TAG="[$(date -u +%FT%TZ)]"

fail() { echo "$LOG_TAG business backup FAILED: $*" >&2; rm -f "$ARCHIVE.tmp"; exit 1; }

# --- 1. resolve which collections are too big to belong in an hourly dump ---
BIG_LIST=$(mongosh "$MONGO_URL" --quiet --eval "
  var db = db.getSiblingDB('$DB_NAME');
  var out = [];
  db.getCollectionNames().sort().forEach(function(c){
    var s = db.getCollection(c).stats();
    if (s.size >= ($BIG_MB * 1048576)) out.push(c);
  });
  print(out.join(' '));
" 2>&1) || fail "mongosh could not enumerate collections: $BIG_LIST"

TOTAL=$(mongosh "$MONGO_URL" --quiet --eval \
  "print(db.getSiblingDB('$DB_NAME').getCollectionNames().length)" 2>/dev/null)
[[ -z "${TOTAL:-}" ]] && fail "could not read collection count from MongoDB"

BIG_N=$(echo "$BIG_LIST" | wc -w)
KEPT=$(( TOTAL - BIG_N ))
[[ "$KEPT" -lt "$MIN_COLLECTIONS" ]] \
  && fail "only $KEPT collections would be dumped (floor $MIN_COLLECTIONS); refusing"

ARGS=()
for c in $BIG_LIST; do ARGS+=(--excludeCollection "$c"); done

# --- 2. dump, keeping stderr so failures stay diagnosable -------------------
ERRS=$(mongodump --uri "$MONGO_URL" --db "$DB_NAME" "${ARGS[@]}" \
        --archive="$ARCHIVE.tmp" --gzip 2>&1 >/dev/null)
RC=$?
[[ $RC -ne 0 ]] && fail "mongodump exit $RC: $(echo "$ERRS" | tail -2 | tr '\n' ' ')"

# --- 3. refuse a suspiciously small archive ---------------------------------
SIZE=$(stat -c %s "$ARCHIVE.tmp" 2>/dev/null || echo 0)
[[ "$SIZE" -lt "$MIN_BYTES" ]] && fail "dump was only ${SIZE} bytes (floor $MIN_BYTES)"

# --- 4. refuse an archive missing the core business collection --------------
if ! python3 -c '
import gzip, sys
with gzip.open(sys.argv[1], "rb") as fh:
    data = fh.read()
sys.exit(0 if b"\x00users\x00" in data else 1)
' "$ARCHIVE.tmp"; then
  fail "dumped archive does not contain a users collection"
fi

# --- 5. publish atomically, then announce -----------------------------------
mv -f "$ARCHIVE.tmp" "$ARCHIVE"
echo "$LOG_TAG business backup OK -> $(basename "$ARCHIVE") (${KEPT} collections, $(du -h "$ARCHIVE" | cut -f1), excluded ${BIG_N}: $(echo $BIG_LIST | tr ' ' ','))"

# --- 6. retention: keep the newest $RETENTION_HOURS ------------------------
# `ls` exits 2 when the glob matches nothing; a first run must not look like a
# failure, so the listing is captured without letting that status escape.
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/biz-*.archive.gz 2>/dev/null | tail -n "+$((RETENTION_HOURS + 1))")
if (( ${#OLD[@]} > 0 )); then
  rm -f -- "${OLD[@]}"
  echo "$LOG_TAG pruned ${#OLD[@]} snapshot(s) older than ${RETENTION_HOURS}h"
fi

exit 0
