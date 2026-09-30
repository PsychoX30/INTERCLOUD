# Network Monitoring Upgrade — Implementation Plan (P0–P1)

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Perbaiki bug auto-heal yang membuat graph baru mati permanen saat ifIndex berubah, lalu tambahkan alerting SNMP dengan memakai ulang infrastruktur notifikasi NOC yang sudah ada.

**Architecture:** Backend FastAPI + MongoDB existing (`backend/portal/monitoring_graphs.py`) memakai pola lease-per-graph, auto-heal berbasis `interface_name`, retensi 3-tier (raw 7d / hourly 90d / daily 730d). Frontend React 19 (`frontend/src/pages/portal/admin/AdminMonitoring.jsx`) memakai Recharts + React Flow. Alerting dipakai-ulang dari modul NOC (`notif_channels` + `dispatch_ddos_notifications` pattern di `backend/portal/emails.py`) — tidak bangun roda baru.

**Tech Stack:** FastAPI 0.110, Motor/MongoDB 8, React 19 (CRA), Recharts, React Flow, APScheduler (in-process).

**Verifikasi di tiap task:** backend `cd /home/support/INTERCLOUD/backend && pytest tests/test_... -v`; frontend `cd /home/support/INTERCLOUD/frontend && npm run build` (production, JSX berubah → wajib rebuild; pakai `NODE_OPTIONS=--max-old-space-size=4096`), lalu deploy via pola existing (git fetch + reset --hard + npm run build + `INTERCLOUD_DEPLOY_PASSWORD=... python3 /home/support/workspace/restart_backend.py`).

---

## Konteks / Fakta Terverifikasi

1. Bug §P0-1: `AdminMonitoring.jsx:1244-1250` — `createBulk` TIDAK mengirim `interface_name`/`interface_index` padahal discovery menghasilkan keduanya (`monitoring_graphs.py:363-364`) dan backend sudah siap menerimanya (`routes/graphs.py:158-161`). Akibat: graph buatan UI tersimpan tanpa identitas interface → `heal_stale_oid` (butuh `interface_name`, `monitoring_graphs.py:662`) langsung `return` tanpa remap. **Auto-heal dead untuk semua graph baru.** Ini regresi dari `29ff7df` (repair script jalan, tapi jalur UI tidak disambungkan).

2. Tidak ada alerting untuk graph/SNMP: `monitoring_graphs.py` 0 hasil grep `alert|notify`. `last_poll_state`/`last_poll_error` sudah disimpan (`:616-635`), UI sudah render badge (`AdminMonitoring.jsx:101-116`), tapi tidak ada push. Infrastruktur NOC sudah ada: `notif_channels` (email/telegram/webhook), model `NotifChannelIn` (`models.py:405`), dispatcher `dispatch_ddos_notifications` (`emails.py:1743`).

3. `ifOperStatus` dibaca saat discovery (`monitoring_graphs.py:366`) tapi tidak dipersist ke doc graph.

4. Auto-refresh frontend 30s (`AdminMonitoring.jsx:496`) vs interval poll graph 20s — chart selalu ~1 poll tertinggal.

---

## P0 — Bug Fixes (1–2 hari)

### Task 1: Sambungkan interface identity ke payload bulk creation

**Objective:** Graph yang dibuat via discovery UI menyimpan `interface_name` + `interface_index` sehingga auto-heal bekerja untuk graph baru.

**Files:**
- Modify: `frontend/src/pages/portal/admin/AdminMonitoring.jsx:1243-1250` (`createBulk`)

**Step 1: Tulis test frontend yang gagal** *(lihat Task 2 dulu untuk pola test frontend; jika tidak ada test runner frontend yang jalan, lewati dan gunakan verifikasi build + E2E manual)*

Belum ada `frontend/src/**/*.test.js` untuk komponen ini — cek: `search_files("*.test.js", target="files", path="frontend/src")` (expected: none). Jika kosong, **YAGNI**: jangan bangun test runner; verifikasi via backend contract test di Task 2.

**Step 2: Patch payload**

```js
const sensorsPayload = pickedSensors.map(sensor => ({
  oid: sensor.oid,
  name: sensor.label || sensor.oid,
  display_name: sensor.label || sensor.oid,
  type: kindToType(sensor.kind),
  unit: sensor.unit || "",
  interface_name: sensor.interface_name || "",
  interface_index: sensor.interface_index || "",
  interface_status: sensor.interface_status || "",
}));
```

(`interface_status` opsional — dimanfaatkan Task 7. YAGNI: hanya name+index yang wajib untuk auto-heal.)

**Step 3: Verifikasi build**

```bash
cd /home/support/INTERCLOUD/frontend && NODE_OPTIONS=--max-old-space-size=4096 npm run build
```

Expected: exit 0, bundle `frontend/build/static/js/main.*.js` diperbarui.

**Step 4: Commit**

```bash
cd /home/support/INTERCLOUD && git add frontend/src/pages/portal/admin/AdminMonitoring.jsx && git commit -m "fix(monitoring): persist interface identity on bulk graph creation so auto-heal works"
```

**Verification (runtime, setelah deploy):** buat graph via UI discovery → `db.monitoring_graphs.find({name: "<graph>"})` → pastikan `interface_name` dan `interface_index` terisi. Lalu simulasikan ifIndex drift (ganti `snmp_oid` dengan OID salah) → dalam satu sweep cycle graph di-repair kembali. (Lihat `repair_graph_oids.py` di `/home/support/workspace/` untuk pola simulasinya.)

### Task 2: Test kontrak backend — backend TERIMA interface identity

**Objective:** Pastikan backend bulk endpoint menerima field `interface_*` dari sensor (regression test agar tidak rusak lagi).

**Files:**
- Modify: `backend/tests/test_graphs_routes.py` (ada — lihat pola mock Mongo route test di `test_monitoring_checks_routes.py`)

**Step 1: Tulis test gagal**

```python
# tambahkan ke test_graphs_routes.py
async def test_bulk_create_persists_interface_identity(mock_db):
    # sensor payload dengan interface_name/index — assert doc tersimpan dengan field tsb
    ...
```

**Step 2: Run — expected FAIL** (jika test dibangun dari payload lama yang tak punya field → setelah Task 1, test harus dikirim dengan field tersebut, sehingga semula FAIL karena field belum dikirim)

**Step 3: Run setelah patch frontend (Task 1) — expected PASS** (backend sudah mendukung sejak `routes/graphs.py:158-161`; test ini mengunci kontrak)

**Step 4: Commit** `chore(monitoring): contract test for interface identity persistence`

### Task 3: Persist interface status + expose di serialize_graph

**Objective:** Graph doc menyimpan `interface_status` (up/down/unknown) supaya UI bisa menampilkan status port.

**Files:**
- Modify: `backend/portal/routes/graphs.py:158-161` (tambah persist `interface_status`)
- Modify: `backend/portal/monitoring_graphs.py:973-1004` (`serialize_graph` — tambah field)
- Test: `backend/tests/test_graphs_routes.py`

**Implementasi:**

```python
# routes/graphs.py, setelah interface_index
if sensor.get("interface_status") is not None:
    doc["interface_status"] = str(sensor.get("interface_status") or "unknown")[:16]

# monitoring_graphs.py serialize_graph
"interface_status": doc.get("interface_status") or "",
```

**Verification:** pytest pass; **catatan caveat**: graph lama tak punya field ini → UI harus treat missing sebagai unknown (Task 7).

### Task 4: Sinkronkan auto-refresh frontend dengan interval poll

**Objective:** Chart refresh mengikuti `interval_seconds` graph, bukan hardcode 30s.

**Files:**
- Modify: `frontend/src/pages/portal/admin/AdminMonitoring.jsx:496` (setInterval 30000 → `Math.max(15000, graph.interval_seconds || 30000)`; minimum 15s untuk hindari hammer saat interval kecil)

**Verification:** build + manual (interval 20s → chart refresh ≤ ~35s, bukan 60s+).

---

## ⚠️ KOREKSI — Klaim Roadmap Lama Salah (baca sebelum Task 4b–4e)

Dokumen `librenms_study_roadmap.md` (G2) dan `librenms_graphing_analysis.md` (§6.2) menyatakan retensi kita **"AVG-only"** sehingga 95th percentile under-estimate setelah 6 jam. **Verifikasi source: klaim itu SALAH di bagian penyebabnya.**

Fakta terverifikasi:

| Klaim lama | Fakta source |
|---|---|
| "kita hanya AVG" | `monitoring_samples.py:244-251` menyimpan `avg`,`max`,`min`,`count`; `:307-314` sama untuk daily. Sejak commit `cbfba2d` — **jauh sebelum roadmap ditulis**. |
| "95th hilang karena storage AVG-only" | Storage **punya** max. Yang hilang: **frontend membuang field `min`/`max`**. |

Bukti frontend membuang:
- `_fetch_hourly` (`monitoring_samples.py:134-140`) dan `_fetch_daily` (`:149-155`) **mengembalikan** `min`/`max` per titik.
- `AdminMonitoring.jsx:784` & `:790-791` — merge hanya memetakan `s.value` → **`min`/`max` dibuang tanpa dipakai**.
- `trafficStats(merged, intervalSec)` (`:133-161`) menghitung `max`/`percentile95` dari **nilai avg-of-bucket** → untuk rentang >6h, p95 memang under-estimate spike. **Symptom benar, sebab salah.**

Kesimpulan: **G2 tetap valid sebagai tujuan**, tapi implementasinya berubah total — bukan migrasi schema, cukup (a) teruskan `min`/`max` ke frontend, (b) render envelope MAX/AVG, (c) hitung p95 dari series yang benar. Tidak perlu backfill, tidak perlu migrasi data.

---

## P0-B — Akurasi Graph & Timeframe (koreksi G2 — 1–2 hari)

### Task 4b: Teruskan min/max ke merge dan chart

**Objective:** `min`/`max` per bucket yang sudah dikirim API tidak lagi dibuang; chart bisa render envelope.

**Files:**
- Modify: `frontend/src/pages/portal/admin/AdminMonitoring.jsx:771-794` (`merged` useMemo)

`merged` harus membawa 4 series per titik: `in`, `out`, `inMax`, `outMax` (opsional `inMin`/`outMin` bila mau band). Jangan ubah `samples`/`pairSamples` dulu — cukup tambahkan saat mapping di `byBucket`.

**Verification:** build; buka 1W → `console`/React DevTools pastikan row punya `inMax`. **Catatan jujur:** butuh cek runtime nyata; tanpa itu klaim belum terbukti.

### Task 4c: Render MAX envelope (parity LibreNMS `AREA:inbits_max` + `AREA:inbits`)

**Objective:** Chart menunjukkan peak antar-poll, bukan hanya rata-rata bucket — perilaku `generic_data.inc.php` (AREA MAX warna terang + AREA AVG warna gelap).

**Files:**
- Modify: `AdminMonitoring.jsx:831-848` (chart traffic) — tambah `<Area dataKey="inMax">` fill terang di belakang `<Area dataKey="in">`; idem OUT. Y-axis domain harus menghitung series max juga (`:808-814, 821-825`).

**Verification:** 1W view → area terang tampak di atas garis rata-rata. Bandingkan angka Max di tabel vs puncak area.

### Task 4d: Simpan & pakai p95 asli dari rollup

**Objective:** 95th percentile akurat di semua rentang.

**Files:**
- Modify: `backend/portal/monitoring_samples.py` — tambah `p95` ke doc hourly (`:244-251`) & daily (`:307-314`); agregasi daily pakai rata-rata p95 bobot `count` (atau max-of-p95, pilih dan dokumentasikan).
- Modify: `_fetch_hourly`/`_fetch_daily` (`:134-155`) — sertakan `p95`.
- Modify: `AdminMonitoring.jsx` `trafficStats` — pakai `p95` dari server bila ada; fallback ke perhitungan lama untuk titik raw.
- Migrasi: doc lama tidak punya `p95` → **fallback wajib**, jangan asumsikan ada. Backfill opsional (raw masih ada 7 hari).

**Verification:** pytest; bandingkan p95 1D (hourly) vs p95 dihitung dari raw 1H — harus konsisten dalam toleransi.

### Task 4e: Fix timeframe — preset membekukan `to` (BUG NYATA)

**Bug terverifikasi:** `setRange(hours)` (`:404-416`) menetapkan `from` **dan `to`** sebagai ISO tetap pada waktu klik. `refreshData` (`:473-482`) → `loadData(expandedId)` tanpa `opts` → jatuh ke `from`/`to` state (`:452-453`) yang **beku di waktu klik**. Akibat: setelah pilih preset, window berhenti maju — data baru tidak pernah muncul sampai preset diklik ulang. Tanpa preset (state kosong) justru benar, karena fallback `Date.now()` dihitung ulang tiap panggilan. **Inkonsisten dan terkonfirmasi dari kode.**

**Fix:** simpan preset sebagai **durasi** (`rangeHours`), bukan `to` absolut; hitung `to = Date.now()` tiap muat bila mode preset aktif. Custom range tetap pakai `to` absolut (memang disengaja).

**Verification:** pilih 1D → tunggu 2 menit → titik terbaru bertambah tanpa klik ulang. Ini **wajib diverifikasi runtime**, jangan klaim dari kode saja.

### Task 4g: Retensi data < timeframe yang ditawarkan (GAP NYATA — "1Y kosong")

**Gap terverifikasi:** UI menawarkan preset **1M** dan **1Y** (`AdminMonitoring.jsx:417-423`), tapi retensi kita:

| Tier | TTL | Rentang efektif |
|---|---|---|
| raw | 7 hari (`monitoring_samples.py:190`) | 7 hari |
| hourly | 90 hari (`:198`) | 90 hari |
| daily | 730 hari (`:206`) | 730 hari |

Rantai masalahnya:
1. Preset 1Y = 365 hari → `_resolve_tier` (`:47-48`) pilih `daily` → data ada (daily TTL 2 tahun). **Tapi** daily hanya punya **1 titik per hari** → 365 titik untuk setahun, dan **p95 per hari dari 24 titik** sangat kasar.
2. Preset 1M = 30 hari → `daily` → hanya **30 titik**. Padahal `hourly` (90 hari, jauh lebih detail) **tersedia** — tapi tidak dipakai karena `_resolve_tier` hanya lihat *span*, bukan *ketersediaan tier*.
3. `hourly` TTL 90 hari → **regresi senyap pada hari ke-91**: preset 1M yang tadinya 720 titik berubah jadi 30 titik, tanpa pesan apa pun. Pengguna melihat "grafik tiba-tiba jelek/kosong".
4. **Tidak ada** konsolidasi 7d→30d (mirip RRA `AVERAGE:0.5:6:1440` LibreNMS yang menyimpan 30 hari @30 menit). Celah antara raw 7 hari dan daily 1 hari **kosong**.

**Konsekuensi:** preset 1M/1Y secara teknis "ada data" tapi presentasinya tidak akurat untuk billing — persis keluhan user. Ini gap yang di dokumen lama **tidak tercatat sama sekali**.

**Fix yang diusulkan:**
- Tambah tier/consolidasi **7d→30d** (bucket 30 menit–2 jam, TTL ~180 hari) untuk mengisi celah 7h–90h, atau naikkan TTL `hourly` sesuai kebutuhan billing.
- `_resolve_tier` harus mempertimbangkan **ketersediaan data**, bukan hanya span (mis. pilih hourly bila daily terlalu kasar dan hourly masih ada).
- Beri tahu pengguna saat resolusi turun karena TTL (mis. `resolution: "daily (hourly expired)"`), jangan senyap.

**Verification:** query agregat prod untuk konfirmasi rentang data nyata per tier (jangan asumsikan TTL = data ada); bandingkan jumlah titik 1M sebelum/sesudah fix.

### Task 4f: Indikator preset aktif + CSV export (kosmetik, opsional)

- Highlight preset yang aktif; tombol clear saat custom range dipakai.
- Export CSV di UI (backend `routes/graphs.py` sudah punya export; cek apakah CSV tersedia untuk UI — jika hanya PDF, tambahkan).

---

## Revisi Prioritas Roadmap Lama

| Roadmap lama | Status setelah verifikasi |
|---|---|
| P0 "quantile retention" (2 hari, migrasi schema) | **Superseded** → ganti P0-B Task 4b–4d (≤1 hari, tanpa migrasi) |
| P1 alerting | **Tetap valid** → P1 Task 5–8 di bawah |
| "MIN/MAX hilang setelah 6 jam" | **Salah** — min/max tersimpan; yang hilang adalah pemakaiannya di UI |
| "p95 belum ada" | **Benar** — rollup belum simpan `p95` (Task 4d) |
| Timeframe "sudah sama dengan LibreNMS (tier selection)" | **Tidak sepenuhnya** — ada bug preset membekukan `to` (Task 4e) |
| Retensi vs preset yang ditawarkan | **GAP BELUM TERCATAT** → Task 4g (1M hanya 30 titik; hourly expired hari ke-91 tanpa peringatan) |
| Cadence 20s "lebih baik dari LibreNMS" | **Benar tapi jangan dibanggakan** — 3 poll pada interface 40Gbps kena wrap counter 32-bit; efektif aman ~5.4 Gbps. Lihat catatan di §Menjawab "kenapa LibreNMS lebih akurat" |

---

## P1 — Alerting SNMP (3–5 hari)

### Task 5: Model + CRUD alert rule untuk graph

**Objective:** Admin bisa define threshold rule per graph/metric (state error, capacity, dll).

**Files:**
- Modify: `backend/portal/models.py` (tambah `GraphAlertRuleIn`/`Out` setelah `NotifChannelIn`/`Out`)
- Create: `backend/portal/routes/graph_alerts.py` (atau tambah ke `routes/graphs.py` — pilih yang lebih bersih; `routes/graphs.py` sudah 545 baris, lebih baik file baru)
- Test: `backend/tests/test_graph_alerts_routes.py` (pola mock: `test_monitoring_checks_routes.py`)

**Model draft:**

```python
class GraphAlertRuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    graph_id: str
    metric: Literal["state_error", "traffic_bps", "percent"] = "state_error"
    operator: Literal[">", ">=", "<", "<="] = ">"
    threshold: float = Field(gt=0)
    # jumlah siklus berturut-turut sebelum alert (debounce)
    consecutive: int = Field(default=2, ge=1, le=50)
    channels: List[str] = []  # notif_channel _ids; kosong = pakai semua enabled
    enabled: bool = True
```

**Verification:** pytest pass; curl/API smoke `GET /admin/monitoring/alert-rules` → `[]`.

### Task 6: Evaluator alert di dalam graph sweep + dispatch

**Objective:** Rule dievaluasi tiap sweep; transisi → dispatch notifikasi via channel.

**Files:**
- Modify: `backend/portal/monitoring_graphs.py` (hook di `_record_graph_status` atau setelah `_one()` di `run_graph_sweep`)
- Modify: `backend/portal/emails.py` (tambah `dispatch_graph_alert_notifications(db, alert)` — **copy pola `dispatch_ddos_notifications` (`emails.py:1743-1810`), reuse `deliver()` email, `iv2.TelegramNotifier`, webhook httpx**)
- Test: `backend/tests/test_graph_alerts_dispatch.py`

**Algoritma (state machine per rule):**

```
for rule in enabled rules:
    if metric == "state_error":
        state = graph.last_poll_state
        if state == "error": streak++
        else: streak = 0
        if streak == rule.consecutive: FIRE (new alert row + dispatch)
        if state == "ok" and last_alert_fired: RESOLVE (update alert row, dispatch "recovered")
```

**Skema alert row:** `monitoring_graph_alerts` (opened_at, resolved_at, graph_id, rule_id, message, status `active|resolved`, notified).

**Penting:** evaluasi **hanya transisi** (open/resolve) — mirror `monitoring_events` di ping checks (`monitoring.py:68-69`). Jangan re-dispatch tiap siklus (spam). Gunakan `notif_channels` yang sudah ada; tambah nilai "graph" ke `events` list (`NotifChannelIn.events` → `["ddos", "graph"]`).

**Retensi alert:** index TTL 90d di `server.py` + `monitoring_graph_alerts` (pola `monitoring_graph_samples_hourly`).

**Verification:** unit test mock → streak 2 → dispatch terpanggil sekali; lalu state ok → resolve terpanggil. Tidak ada dispatch saat streak 1.

### Task 7: UI — health ringkasan + tab Alert Rules + badge interface status

**Objective:** Operator melihat "N graph error", mengelola rule alert, dan melihat status port tanpa buka tiap graph.

**Files:**
- Modify: `frontend/src/pages/portal/admin/AdminMonitoring.jsx` (banner agregat di atas list + kolom status `interface_status` di discovery results; sedikit — 30–60 baris)
- Tab baru "Alert Rules" (CRUD tabel + form modal) — route: `react-router` lazy import di `App.js` (pola: `AdminMonitoring` lazy; lihat `App.js` route entry existing)

**Verifikasi:** build + browser smoke (Playwright pola `/tmp/novnc_test_venv` — kalau venv hilang, gunakan `browser_exec`, atau API smoke: POST rule → GET list → PUT disable → DELETE).

### Task 8: Maintenance window sederhana

**Objective:** Admin bisa redam alert saat maintenance (versi minimal; tidak perlu scheduler penuh).

**Files:**
- Model + endpoint: `maintenance_windows` collection (start/end/graph_ids/note)
- Evaluator Task 6: skip rule jika `now` dalam window yang mencakup graph tsb.

**Verification:** unit test — rule ter-suppress dalam window, normal di luar.

---

## P2+ (BACKLOG — tidak dikerjakan sekarang)

- **Entity Device + credential inheritance** (hapus 20× salinan kredensial; 1-2 minggu) — perlu migrasi data besar, keputusan desain, jangan dicampur sprint ini.
- **Enkripsi kredensial SNMP** via `secretbox.py` (Fernet) — security hardening, sprint terpisah.
- **Auto-discovery LLDP/CDP** untuk Network Map — kompleksitas tinggi.
- **Capacity planning / forecast** — butuh model data baru.
- **Export CSV** — kecil, bisa jadi task tambahan.
- **Selaraskan ClientMRTG/ClientTraffic** — UX, sprint terpisah.

---

## Urutan Kerja & Dependencies

```
Task 1 → Task 2 → Task 3 → Task 4     (P0-A; bug auto-heal; risiko rendah)
Task 4b → 4c → 4d → 4e → (4f)         (P0-B; akurasi graph + timeframe; tanpa migrasi)
Task 5 → Task 6 → Task 7 → Task 8     (P1; butuh Task 5 dulu)
```

Deploy batch: P0-A+P0-B sekali deploy (satu build frontend + satu restart backend). Task 5–8 batch kedua.

**Catatan urutan:** Task 4e (timeframe) bisa dikerjakan paralel dengan 4b–4d (chart) — file sama (`AdminMonitoring.jsx`) tapi region berbeda. Jika dikerjakan paralel di working tree yang sama, **jangan** dua agen menyentuh file yang sama (lihat skill `concurrent-repository-safety`) — kerjakan berurutan atau pisah branch.

## Files Likely to Change (ringkas)

| File | Jenis perubahan |
|---|---|
| `frontend/src/pages/portal/admin/AdminMonitoring.jsx` | payload identity (T1), refresh (T4), UI alert (T7) |
| `backend/portal/routes/graphs.py` | persist interface_status (T3) |
| `backend/portal/monitoring_graphs.py` | serialize + evaluator alert (T3, T6) |
| `backend/portal/models.py` | `GraphAlertRuleIn/Out` (T5) |
| `backend/portal/routes/graph_alerts.py` | CRUD baru (T5) |
| `backend/portal/emails.py` | `dispatch_graph_alert_notifications` (T6) |
| `backend/server.py` | index TTL alert collection (T6) |
| `backend/tests/*` | test baru + kontrak (T2, T5, T6) |

## Tests / Validation

- Backend: `cd /home/support/INTERCLOUD/backend && pytest tests/test_graphs_routes.py tests/test_graph_alerts_routes.py tests/test_graph_alerts_dispatch.py -v` (semua PASS). Full suite: 54+ test (catatan: 8 collection failure terkait `REACT_APP_BACKEND_URL` di env — bukan regresi).
- Frontend: `npm run build` exit 0.
- E2E prod: Playwright pola `/tmp/novnc_test_venv/bin/python`; jika venv hilang → smoke via API `requests` + `browser_exec`.
- Evidence: tangkap output pytest, build log, curl response, Mongo query.

## Risks / Tradeoffs / Open Questions

1. **Risk:** `interface_status` legacy graph missing → `undefined` di frontend. Mitigasi: fallback `"unknown"`.
2. **Risk:** debounce alert `consecutive` — nilai default 2 siklus untuk `state_error`; untuk `traffic_bps`, window 2× interval cukup (traffic spike natural 1 siklus jangan langsung alert). Default `consecutive >= 2`.
3. **Tradeoff:** evaluator di `run_graph_sweep` (in-process) vs service terpisah — in-process sesuai arsitektur existing (sweep sudah ada, lease per-graph, failure isolation); service terpisah overkill untuk skala 6–50 graph.
4. **Open Q:** apakah alerting graph boleh kirim ke channel yang sama dengan DDoS (event `graph` ditambahkan ke `NotifChannelIn.events`)? Asumsikan ya, konfigurasi per-channel memisahkan.
5. **Open Q:** notifikasi bahasa Indonesia (selaras `dispatch_ddos_notifications`) — asumsikan ya.
6. **Open Q (deploy):** Task 1–4 deploy ke prod memakai pola `reset --hard` pada branch saat ini (`feature/foldering-sharing-overhaul`? pastikan branch saat deploy sesuai repo `git status`/`git branch` — jangan reset ke main jika pekerjaan aktif di branch fitur).

## Non-Goal (explicit)

- Tidak ada enkripsi kredensial SNMP sekarang (P2).
- Tidak ada entity Device/migrasi data (P2).
- Tidak ada auto-discovery topologi (P2).
- Tidak ada perbaikan halaman client (P2).
- Tidak ada perubahan schema besar / migrasi data.