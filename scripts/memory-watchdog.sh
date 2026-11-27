#!/bin/bash
# Recycle the backend workers when a single worker's RSS approaches the level
# that previously triggered global OOM kills (7.9 GB anon-RSS -> kernel killed
# a random python worker, and would have considered mongod too).
#
# Threshold rationale: steady state is ~300-500 MB per worker. 2500 MB is far
# above any legitimate peak but far below the point where the kernel starts
# making global decisions. Debounced over 3 samples so a transient report spike
# never triggers it.
#
# Restarting is the *safe* direction: supervisor brings the workers back in ~3 s
# and no data is lost (all state is in MongoDB). The alternative -- a kernel OOM
# kill -- picks its victim by RSS and can take mongod with it.
set -uo pipefail
APP_DIR="${APP_DIR:-/opt/intercloud-portal}"
LIMIT_MB="${LIMIT_MB:-2500}"
STATE=/var/tmp/memory-watchdog.count
LOG=/var/log/intercloud-memory-watchdog.log

maxrss=0; maxpid=0
for pid in $(pgrep -f 'server:app' 2>/dev/null); do
    rss=$(awk '/^VmRSS/{print int($2/1024)}' "/proc/$pid/status" 2>/dev/null)
    [ -z "${rss:-}" ] && continue
    if [ "$rss" -gt "$maxrss" ]; then maxrss=$rss; maxpid=$pid; fi
done

if [ "$maxrss" -eq 0 ]; then
    echo "0" > "$STATE"; exit 0
fi

if [ "$maxrss" -ge "$LIMIT_MB" ]; then
    n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STATE"
    echo "$(date -u +%FT%TZ) HIGH MEMORY sample $n/3: pid=$maxpid rss=${maxrss}MB limit=${LIMIT_MB}MB" >> "$LOG"
    if [ "$n" -ge 3 ]; then
        echo "$(date -u +%FT%TZ) ACTION restart intercloud-backend (rss=${maxrss}MB sustained 3 samples)" >> "$LOG"
        supervisorctl restart intercloud-backend >> "$LOG" 2>&1
        echo "0" > "$STATE"
    fi
else
    echo "0" > "$STATE"
fi
