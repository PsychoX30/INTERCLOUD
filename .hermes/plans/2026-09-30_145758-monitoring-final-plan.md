# Network Monitoring Upgrade — PLAN FINAL: Better than LibreNMS, Zero Surprise Bugs

> **Date:** 2026-09-30 14:58 UTC · **Status:** Adopted (user: "adopsi semua saran dan rekomendasimu, buat plan")
> **Supersedes:** `2026-09-30_140500-monitoring-upgrade-p0-p1.md` (keep for history; this plan is authoritative)
> **Fakta basis:** source-read local repo `fa013171` + live prod query. Verifikai MONGO prod real-time, bukan dugaan.

---

## TL;DR — What Changed vs Old Plan (3 Big Findings)

Verifikasi menyeluruh menemukan **3 masalah yang lama tidak terdicetek dan justru menjawab kekhawatiranmu "bug tiba-tiba jangka panjang"**:

| # | Temuan | Severity | Jawab |
|---|---|---|---|
| **F1** | **`ddos_samples` (3.5M docs) tanpa index, semua query COLLSCAN + ISO string** → mongod 98% CPU, bi 78k blok/s (40MB/s), swap 3.9G terpakai, load 6.2 | 🔥 CRITICAL — PROD LAG | Index + migrasi type + TTL (Task 0) |
| **F2** | **`monitoring_probes` (104k docs, since Aug 13) UNBOUNDED** — no TTL/index+at | 🔥 HIGH | TTL 90d (Task 0b) |
| **F3** | **10/12 schedule leases stuck STALE** — `job:graph_downsample` expiry Aug 14 (4 graphs), `job:graph:*` orphan 30+ | 🔥 HIGH — CELAH DOWNSAMPLE GROUPING | Cleanup + fix group key (Task 0c) |

Plus: raw graph coverage **diverges 3%–52%** (graph lama vs baru — poll gap real), dan `hourly` datanya dipakai tapi `min/max` dibuang frontend (F4-b, F4-c lama).

**Konsekuensi:** sebelum tambah akurasi/tier/manajemen, **MUST fix produksi sedang lagg** (F1-F3) dulu.

**Decision Framework User:** target = "sistem lebih baik dari librenms tanpa bug dan error jangka panjang yang tiba tiba muncul".

**Prioritas:**
1. **Reliability** — mendirancang produksi aman (F1-F3) sebelum add anything.
2. **Correctness** — akurasi graph (p95, envelope, timeframe) tanpa regresi.
3. **Parity-plus** — features LibreNMS yang memberi nilai (envelope, percentile, maintenance) dengan kami arsitektur.
4. **Observability** — kami juga butuh alarm saat penghasilamak (dokumentasi, graph health, nix limits).

---

## Executif Summary — Verifikasi (semua evidence source-backed)

**Prod facts (queried live, 2026-09-30 14:45-14:58 UTC):**
| Metric | Actual | Expected | Verdict |
|---|---|---|---|
| mongod CPU | **98%** | <50% | 🔥 CRITICAL |
| load average (4 core) | **6.2** | <2 | 🔥 CRITICAL |
| disk read `bi` | **78k B/s (≈40MB/s)** | <10k | 🔥 CRITICAL |
| swap used | **3.9G (100%)** | 0 | 🔥 CRITICAL |
| `ddos_samples` docs | **3,528,241** | bounded | 🔥 CRITICAL (no index, ISO string) |
| `monitoring_probes` docs | **104,165** | bounded | 🔥 HIGH (no TTL) |
| raw coverage 7d (6 graphs) | **3%–52%** | 100% | 🔥 HIGH (graph gap) |
| `job:*` stale leases | **30+** (expiry Aug 13-14) | 0 | 🔥 HIGH |
| RAW TTL (7d) | OK | OK | ✅ |
| Hourly TTL (90d) | OK | OK | ✅ |
| Daily TTL (730d) | OK | OK | ✅ |
| `interface_*`-identity persisted (all 6) | OK | OK | ✅ |
| graph last_poll_state | all `ok` | OK | ✅ |
| hourly data span | 47d (Aug 14→Sep 30) | OK | ✅ |

**Evidence source:** prod scripts `prod_diag.py`, `prod_diag_final.py`, `prod_verify_types.py` (read-only, pymongo via backend venv). Local: `monitoring_samples.py:1-330`, `monitoring.py:1-218`, `integrations_v2.py:1046-1140`, `emails.py:1480-1620`, `server.py:133-209`, `AdminMonitoring.jsx:395-500, 600-650, 771-794, 803-931`.

---

## F1 — `ddos_samples` COLLSCAN critical (P0, day 1)

**Root cause chain (source + live verified):**
1. `emails.py:1607` `insert_one(sample)` — sample store `at` as **ISO string** (line `sample = {"at": now_iso, ...}` where `now_iso = now.isoformat()`).
2. `emails.py:1610` `find({"key": ..., "at": {"$gte": cutoff}}) .to_list(100)` — **no index** mapping. Index build on `({"key":1, "at":-1})` or `({"at":-1, "key":1})`.
3. `ddos_samples` has **only `_id` index** (verified live: `idx=1`), so each query = **COLLSCAN 3.5M docs**, ~1.8s, **every 10s** (`CronTrigger(second="*/10")` at `emails.py:2434`).
4. **MongoDB TTL index only works on BSON `Date`** — ISO string field would **never** expire. So even adding TTL later on `at` without a data-type migration would silently fail to clean up.
5. **Disk/mem:** 3.5M docs × ~160B ≈ 565MB logical, 120MB storage — the scan **reads the entire collection per query**. Combined with 24% system cpu + mongod 98% → this is the primaryLoad.

**Fix (Task 0a):**
- Create compound index `{"key":1, "at":-1}` (query-shape: `key` equality + `at` range). Also `{"at":-1}` secondary for TTL cleanup.
- **Data migration:** convert `at` string → BSON `datetime` (idempotent; iterate `find({at: {$type: "string"}})` and `update_one` with `datetime.fromisoformat`). Then **TTL index** `expireAfterSeconds=7*86400` on new `at` (field now Date).
- **Code fix:** `emails.py:1607` — store `at` as `datetime` (not ISO string); `emails.py:1610` — use `datetime` cutoff object (not str).
- **Backfill:** cleanup before deploying: `delete_many({"at": {"$lt": now-7d}})` after migration (or rely on TTL once index exists).
- **Verification:** `explain()` on the query → `IXSCAN`; rerun `prod_diag_final.py` → mongod CPU <30%, load <2 after restart? (careful: restart may be needed to clear WT cache, but indexes will take effect immediately). **Evidence: `db.ddos_samples.getIndexes()` shows new index; `explain()` shows `IXSCAN`; CPU/load verified live.**

**Pitfall (memorized):** TTL on string = silently no-op. Always check BSON type before TTL.

---

## F2 — `monitoring_probes` unbounded (P0, day 1)

**Evidence:**
- `server.py:209` creates index `("check_id",1),("at",-1)` but **no TTL** — collection grows forever.
- 104k docs since Aug 13, ~2.1k/day. No retention.
- Route `monitoring.py:143` reads recent N per check (limit(limit)) — but write side has no cleanup.

**Fix (Task 0b):**
- Add TTL index `{"at": 1}, expireAfterSeconds=90*86400` (keep 3 months).
- Aligned with `monitoring_graph_samples_hourly` TTL 90d (consistent).
- **Verification:** `getIndexes()` shows expiry.

---

## F3 — stale scheduler leases + downsample gap (P0, day 1)

**Evidence (live scheduler_leases dump):**
- `job:graph_downsample` expiry **Aug 14 02:41** — downsample aggregation has not run for the **old graph cohort** (raw 52% coverage at 6a7ec..., 3% for 6a7e7.../6a7f3...) — because 8-slot group? No — inspect: `downsample_raw_to_hourly` has no `graph_id` filter, loops all raw, but `job:graph_downsample` last run Aug 14 suggests **the job may have crashed/failed**; or the newer downsample sweep (`run_downsample_sweep`) runs on the **all-graph** list but job id fixed → after the Aug 14 run, later runs may have been failing silently.
- **30+ stale `job:graph:*`** leases from Aug 13-14 (old test graphs?) hold lease forever (expired leases aren't reaped — `acquire_scheduler_lease` sees expiry and acquires, but **stale rows pollute**; and `job:graph:6a7c32...` etc. were from old graph ids that no longer exist).
- **Orphans** (`job:graph:*` for deleted graphs) accumulate — collection `scheduler_leases` has 44 docs, 30+ stale.

**Fix (Task 0c):**
- **Cleanup:** `delete_many` stale `job:graph:*` where graph no longer exists, and expired leases.
- **Code:** `run_downsample_sweep` (or `downsample_raw_to_hourly`) — add `graph_id` filter/loop per graph so a crashed single graph doesn't block the whole sweep (failure isolation like sweep does).
- **Code:** after `_release_scheduler_lease`, also `delete_many` leases that are expired and orphaned (or a reaper in `start_scheduler`).
- **Verify:** rerun sweep → `hourly` counts increase; raw coverage → 100%; leases now only active.

---

## P0-A — Auto-Heal Identity Regression (was P0-1; still valid)

### Task 1: Persist interface identity from discovery → bulk create (blocker for auto-heal on NEW graphs)
- **Evidence:** `AdminMonitoring.jsx:1243-1250` `createBulk` maps only `oid, name, display_name, type, unit` → drops `interface_name`/`interface_index` even though discovery provides them (`monitoring_graphs.py:363-364`) and backend accepts them (`routes/graphs.py:158-161`).
- All 6 CURRENT graphs have identity (verified), so live graphs are healed — **but any new graph created via the UI will NOT get auto-heal**. This is the regression to fix.
- **Fix:** add `interface_name`, `interface_index`, `interface_status` to payload mapping.
- **Verify:** UI-created graph carries the fields; simulate stale OID → auto-heal within a sweep.

### Task 2: Contract test for interface identity (regression guard)
- Add route test in `test_graphs_routes.py` → assert fields persisted.

### Task 3: Persist + expose `interface_status` (chips in UI; decl lock for Task 7 layout)
- `routes/graphs.py` persist; `serialize_graph` emit; UI treats missing as "unknown".

### Task 4: Sync auto-refresh to graph interval (hardcoded 30s → `max(15s, interval)`)
- Verified `AdminMonitoring.jsx:496` 30000 fixed.

---

## P0-B — Graph Accuracy & Timeframe (was P0-B; adopt + verified)

### Task 4b: Keep min/max through merge (currently dropped)
- `AdminMonitoring.jsx:784,790-791` only map `s.value`; `min`/`max` exist in API (`monitoring_samples.py:136,151`) but are dropped.
- Merge must carry `inMax`/`outMax` (+ optional min).

### Task 4c: Render MAX envelope (LibreNMS parity: `AREA:in_max` + `AREA:in`)
- Verbatim: `generic_data.inc.php:149-158` — `AREA:in_max` + `AREA:in` (and `dout_max` + `dout`). Chart needs both Area layers; stats table keeps MAX.

### Task 4d: Compute & persist true p95 in rollups
- `monitoring_samples.py:244-251` currently stores avg/max/min/count — **no p95**. `daily` likewise.
- Add `p95` field: hourly p95 = sorted raw values in hour; daily p95 = weighted (by count) average of hourly p95, or max-of-p95 — **document choice** (recommend weighted by count, matching RRD's percentile semantics).
- `_fetch_hourly`/`_fetch_daily` include `p95`.
- Frontend uses server p95 if present, falls back to local calc for raw.
- **Fallback mandatory** for old docs without p95.

### Task 4e: Fix timeframe preset freezes `to`
- `AdminMonitoring.jsx:404-416` — `setRange(hours)` sets `from` and `to` to fixed ISO; `refreshData` → `loadData()` with no opts → `from`/`to` state → frozen at click time. No preset → `Date.now()` fallback → shifting correctly. **Inconsistent, verified.**
- Fix: preset = duration (`rangeHours`); compute `to=Date.now()` each fetch. Custom range keeps absolute `to`.

### Task 4f: (optional) active-preset highlight + CSV export
- Minor.

---

## P0-C — NEW: Production Reliability & Long-Term Bug Prevention (your explicit ask)

### Task 0d: Add a **health endpoint + watchdog** for graph/collection health
- Extend `GET /admin/monitoring/graphs` or new `/admin/monitoring/health` with:
  - per-graph raw/hourly/daily counts vs expected (coverage %),
  - collection sizes and TTL status (`db.collection` stats),
  - stale lease count,
  - mongod `currentOp` slow ops sample.
- Cron `snmp_cadence_watchdog.py` (exists) extended to alert when coverage <90% or collections unbounded.

### Task 0e: Retention policy central config
- Single config dict: `RAW_TTL_DAYS=7`, `HOURLY_TTL_DAYS=90`, `DAILY_TTL_DAYS=730`, `PROBES_TTL_DAYS=90`, `DDOS_TTL_DAYS=7`, `ALERTS_TTL_DAYS=90`.
- Applied consistently in `ensure_indexes()` (server.py) + `monitoring_samples.py` + new indexes.
- **Documented** in `README_MEMORY.md`.

### Task 0f (P1): Alerting with **debounce + maintenance window** — already in plan; keep.

---

## P0-D — NEW: Tier Fix — 30-minute tier to match LibreNMS RRA (was Task 4g)

**Problem (verified by live data + math):**
- UI presets: 1H/1D/1W/1M/1Y (`AdminMonitoring.jsx:417-423`).
- Current tier selection (`monitoring_samples.py:37-48`):
  - ≤6h → raw (20s)
  - ≤7d → hourly (1h)
  - >7d → daily (1d)
- **Result:** 1M preset = 30 days → daily → **30 points** (vs LibreNMS 1440 points at 30-min). 1W = 168 hourly points (fine). 1Y = 365 daily points (fine for aggregate, but p95 per day is crude).
- **Gap:** no 30-min tier; hourly TTL 90d; **no consolidation 7d→30d** (RRA `AVERAGE:0.5:6:1440` = 30-min × 30d).

**Target (matching LibreNMS RRA semantics):**
- Add tier `halfhour` (bucket=1800s, TTL=200d or align 180~200) → 1W/1M use 30-min points (336 / 1440 pts).
- 1Y keeps daily (365 pts — acceptable aggregate; optionally add 2-hour tier later).
- 1D keeps hourly (24 pts — matches LibreNMS 5-min? No — 24 pts too coarse; but LibreNMS 1D at 5-min would be 288 pts. **We could use hourly for 1D (24 pts) — still less than LibreNMS 288, but the p95+max now real. Decision: keep 1D → hourly for now; revisit if user wants 1D denser.)**
- `_resolve_tier` must consider **data availability + desired points**, not just span (e.g., if hourly TTL expired for a graph, fall back to daily and note `resolution: "daily (hourly expired)"`).
- **Backfill:** run `downsample_raw_to_hourly` for the new tier (or a new `downsample_raw_to_halfhour`). Existing hourly data at 1h cannot be averaged into 30-min (no raw), so **old data stays hourly; new data fills halfhour**. Acceptable; document.

**RRA-math reference (computed deterministic):**

LibreNMS (step=300s):
| CF | PDP | rows | bucket | span |
|---|---|---|---|---|
| AVERAGE | 1 | 2016 | 300s (5min) | 7d |
| AVERAGE | 6 | 1440 | 1800s (30min) | 30d |
| AVERAGE | 24 | 1440 | 7200s (2h) | 120d |
| AVERAGE | 288 | 1440 | 86400s (1d) | 1440d |

Proposed INTERCLOUD:
| tier | bucket | TTL | max pts |
|---|---|---|---|
| raw | 20s | 7d | 30240 |
| hourly | 3600s | 90d | 2160 |
| halfhour | 1800s | 200d | 9600 |
| daily | 86400s | 730d | 730 |

Preset → tier after fix:
| preset | span | tier | pts |
|---|---|---|---|
| 1H | 1h | raw | 180 |
| 1D | 24h | hourly | 24 |
| 1W | 7d | halfhour | 336 |
| 1M | 30d | halfhour | 1440 |
| 1Y | 365d | daily | 365 |

---

## P1 — Alerting (keep, refinish with debounce)

### Task 5: Alert rule CRUD (model + routes)
### Task 6: Evaluator in sweep + dispatch (state machine, transizioni only)
- Copy `dispatch_ddos_notifications` pattern; add `graph` event to `NotifChannelIn.events`.
- Retentie: TTL 90d on `monitoring_graph_alerts`.
### Task 7: UI — summary badge + Alert Rules tab + interface status chips
### Task 8: Maintenance windows (suppress alerts during window)

---

## Implementation Order & Dependencies

```
Phase 0 (day 1, hotfix to prod, single deploy batch):
  0a F1 index+migration+TTL   → REBOOT backend (scheduler restarts)
  0b F2 monitoring_probes TTL
  0c F3 lease cleanup + downsample isolation
  → VERIFY: mongod CPU <30%, load <2, ddos query IXSCAN, probes bounded

Phase 0.5 (day 1-2, code+test+deploy):
  Task 1 (UI interface identity)
  Task 2 (contract test)
  Task 3 (interface_status persist/expose)
  Task 4 (refresh sync)

Phase 1 (day 2-3, accuracy, single frontend+backend build):
  Task 4b (min/max merge)
  Task 4c (MAX envelope)
  Task 4d (p95 rollup)
  Task 4e (timeframe freezes fix)

Phase 2 (day 3-4, tier):
  Task 4g/0d (halfhour tier + resolver availability + health endpoint + watchdog)

Phase 3 (day 4-6, alerting):
  Task 5-8

Deploy cadence:
  Batch A: Phase 0 (all backend; single sudo deploy + restart)
  Batch B: Phase 0.5 (frontend)
  Batch C: Phase 1+2 (frontend+build, backend)
  Batch D: Phase 3 (full)
```

## Tests / Validation

- Backend: `pytest tests/test_graphs_routes.py tests/test_monitoring_samples.py tests/test_graph_alerts_routes.py tests/test_graph_alerts_dispatch.py -v` — all PASS.
- Frontend: `npm run build` exit 0 (JSX changed → mandatory; NODE_OPTIONS=--max-old-space-size=4096).
- Live verification scripts (read-only + apply):
  - `prod_diag.py` / `prod_diag_final.py` / `prod_verify_types.py` (before/after CPU, load, index, TTL)
  - `explain()` on ddos query → `IXSCAN` (was COLLSCAN)
  - Coverage per graph = 100% (raw 7d, hourly, daily)
  - Run sweep → hourly counts increase; leases only active
- E2E: browser smoke via `browser_exec` (if daemon up) or Playwright `/tmp/novnc_test_venv`; else API smoke.

## Risks / Tradeoffs / Open Questions

1. **Reboot:** adding TTL index + migration may need a backend restart (APScheduler jobs restart); mongod may need `wiredTiger` cache bump? — actually mongod 98% is from COLLSCAN; after index the CPU should drop without restart. **Don't restart mongod** (risk); verify first.
2. **Data migration (F1) is destructive if wrong:** use `update_one` with type check + `$set` datetime; backup first (`mongodump` to `/opt/backup/`); rollback = restore.
3. **halfhour tier:** old hourly data (1h) can't be averaged to 30m — **only new data** gets halfhour; graph shows mixed resolution (document in UI `resolution: "30m (older hourly)"`).
4. **p95:** document weighted-by-count choice; fallback for old docs.
5. **Stale lease cleanup:** after cleaning, ensure `acquire_scheduler_lease` reaps expired rows opportunistically in code (small change).
6. **Avoid scope creep:** P2 (SNMP creds encryption, device entity, LLDP discovery, CSV, client pages) stays backlog.

## Non-Goal (explicit)
- No SNMP credential encryption now (P2).
- No device entity/data migration (P2).
- No LLDP topology auto-discovery (P2).
- No client-page revamp (P2).
- No CSV export now (optional 4f).
- No change to LibreNMS's technology choice; we keep Mongo+React+20s cadence; **we adopt LibreNMS's RRA statistics semantics, not its tooling**.