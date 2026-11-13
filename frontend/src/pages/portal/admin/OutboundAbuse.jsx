import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, formatApiError } from "../../../portal/api";
import { Card, btnPrimary, btnSecondary, btnDanger, inputClass, labelClass } from "../ui";
import {
  Activity, Ban, CheckCircle2, ChevronDown, ChevronRight,
  Loader2, Network, Save, Search, ShieldOff, Undo2, XCircle,
} from "lucide-react";

// The control plane exposes every threshold; the UI is grouped by the question
// the operator is answering, not by the order the fields happen to sit in the
// dataclass. Volume fields live under "gate" because they never block on their
// own — telling an operator otherwise is how a busy-but-legitimate customer
// gets disconnected.
//
// Wording rule for this screen: every label must answer "what do I type here
// and what happens if I get it wrong". Field names copied from the dataclass
// ("dst_diversity_min", "fanout_ratio_min") told a support agent nothing — the
// screen was documented as confusing by the people who have to operate it.
const GROUPS = [
  {
    key: "gate",
    title: "1. Saringan awal — trafik kecil diabaikan",
    hint: "Bagian ini TIDAK PERNAH memblokir apa pun. Fungsinya cuma melewati pelanggan yang trafiknya terlalu kecil untuk dinilai. Salah setel di sini paling parah membuat penilaian meleset, bukan memutus pelanggan.",
    fields: ["enabled", "window_seconds", "skip_below_pps", "skip_below_bytes", "small_packet_bytes"],
  },
  {
    key: "shape",
    title: "2. Bukti serangan — bentuk trafik yang dinilai",
    hint: "Lima ciri khas serangan. Setiap ciri yang terpenuhi menambah poin. Pelanggan normal yang sedang mengunduh besar TIDAK memenuhi ciri-ciri ini, karena yang dinilai bentuk paketnya, bukan besarnya.",
    fields: ["syn_pps_min", "syn_ratio_min", "dst_diversity_min", "small_pps_min",
             "small_packet_ratio_min", "fanout_min_syn", "fanout_ratio_min"],
  },
  {
    key: "decision",
    title: "3. Kapan benar-benar diblokir",
    hint: "Poin dari bagian 2 dijumlahkan. Blokir hanya terjadi bila poin cukup DAN cukup banyak ciri terpenuhi DAN bertahan beberapa kali pengamatan berturut-turut. Naikkan angka di sini kalau masih ada pelanggan sah yang ikut diblokir.",
    fields: ["min_score_to_block", "min_signals_to_block", "confirm_windows",
             "instant_critical_pps", "instant_critical_syn_ratio",
             "instant_confirm_windows"],
  },
  {
    key: "penalty",
    title: "4. Lama blokir untuk pelanggar berulang",
    hint: "Pelanggaran pertama diblokir sebentar. Kalau diulang, durasinya bertambah. Isi -1 artinya blokir permanen sampai dicabut manual dari tombol \"Cabut blokir\".",
    fields: ["penalty_ladder_hours", "penalty_memory_days"],
  },
];

// Plain-language label + a one-line "what this means" for each stored field.
const LABELS = {
  enabled: "Aktifkan pemantauan serangan keluar",
  window_seconds: "Lama satu kali pengamatan (detik)",
  skip_below_pps: "Abaikan bila di bawah (paket/detik)",
  skip_below_bytes: "Abaikan bila di bawah (byte per pengamatan)",
  small_packet_bytes: "Ukuran paket dianggap \"kecil\" (byte)",
  syn_pps_min: "Permintaan koneksi baru per detik",
  syn_ratio_min: "Porsi paket \"minta konek\" (0-1)",
  dst_diversity_min: "Jumlah tujuan berbeda",
  small_pps_min: "Paket kecil per detik",
  small_packet_ratio_min: "Porsi paket kecil (0-1)",
  fanout_min_syn: "Minimal permintaan konek sebelum dicek balasannya",
  fanout_ratio_min: "Perbandingan minta-konek : dibalas",
  min_score_to_block: "Poin minimum untuk blokir (0-5)",
  min_signals_to_block: "Minimal ciri serangan terpenuhi (dari 4)",
  confirm_windows: "Harus terjadi berapa kali berturut-turut",
  instant_critical_pps: "Paket/detik yang langsung diproses cepat",
  instant_critical_syn_ratio: "Porsi minta-konek yang langsung diproses cepat (0-1)",
  instant_confirm_windows: "Konfirmasi tambahan sebelum blokir darurat",
  penalty_ladder_hours: "Lama blokir bertingkat (jam)",
  penalty_memory_days: "Ingat pelanggaran selama (hari)",
};

// Fraction-valued fields. The stored value is a ratio (0.60), not 60. Every
// label that used to say "%" taught the operator to type 60, which the parser
// then accepted as 6000 % — the threshold silently became impossible to reach.
const RATIO_FIELDS = new Set([
  "syn_ratio_min", "small_packet_ratio_min", "instant_critical_syn_ratio",
]);

const HELP = {
  enabled: "Kalau dimatikan, tidak ada penilaian sama sekali.",
  window_seconds: "Trafik dikumpulkan selama ini lalu dinilai sebagai satu kesatuan.",
  skip_below_pps: "Pelanggan dengan trafik sepi dilewati. Ini penghemat kerja, bukan ambang bahaya.",
  skip_below_bytes: "Sama seperti di atas, dalam satuan byte.",
  small_packet_bytes: "Batas ukuran paket yang dianggap kecil. Paket serangan biasanya di bawah 100 byte.",
  syn_pps_min: "Serangan biasanya membanjiri dengan permintaan koneksi. Pengguna normal: puluhan per detik.",
  syn_ratio_min: "Ditulis desimal. Isi 0.6 artinya 60% dari paket adalah permintaan konek. Pengguna normal: di bawah 0.1.",
  dst_diversity_min: "Menyerang banyak alamat sekaligus. Pengguna normal menghubungi belasan tujuan, bukan ratusan.",
  small_pps_min: "Banjir paket kecil tanpa isi, ciri khas serangan volumetrik.",
  small_packet_ratio_min: "Ditulis desimal. Isi 0.85 artinya 85% paket berukuran kecil. Pengguna normal: di bawah 0.3.",
  fanout_min_syn: "Supaya pengecekan balasan tidak membebani router pada trafik sepi.",
  fanout_ratio_min: "Kalau banyak permintaan konek tapi hampir tidak ada balasan, targetnya tidak melayani. Isi 10 artinya 10 kali lebih banyak minta daripada dibalas.",
  min_score_to_block: "Total poin dari kelima ciri, skala 0 sampai 5. Isi 4 artinya minimal empat ciri bernilai penuh.",
  min_signals_to_block: "Dihitung dari empat ciri bentuk (bukan termasuk ciri berulang). Mencegah blokir karena satu ciri kebetulan tinggi.",
  confirm_windows: "Blokir menunggu bukti berulang, bukan satu lonjakan sesaat.",
  instant_critical_pps: "Jalur cepat untuk serangan yang sangat besar, tanpa menunggu konfirmasi biasa.",
  instant_critical_syn_ratio: "Ditulis desimal. Isi 0.8 artinya 80% paket berupa permintaan konek.",
  instant_confirm_windows: "Pengaman supaya jalur cepat tidak salah blokir.",
  penalty_ladder_hours: "Contoh: 0.5, 6, 24, -1. Urutan pelanggaran ke-1, ke-2, ke-3, dst. Isi -1 untuk permanen.",
  penalty_memory_days: "Contoh: 7, 30. Setelah lewat masa ini, pelanggaran dianggap baru lagi.",
};

const SIGNAL_LABELS = {
  S1_syn_flood: "Banjir permintaan koneksi",
  S2_dst_fanout: "Menyerang banyak tujuan",
  S3_small_packets: "Paket kecil bertubi",
  S4_no_return: "Tidak pernah dibalas",
  S5_persistence: "Berulang terus",
};

const ROLE_BADGE = {
  enforcer: "bg-emerald-100 text-emerald-700 border-emerald-300",
  both: "bg-emerald-100 text-emerald-700 border-emerald-300",
  collector: "bg-blue-100 text-blue-700 border-blue-300",
  none: "bg-slate-100 text-slate-600 border-slate-300",
};

// Router roles are storage values; operators read them as jobs.
const ROLE_LABEL = {
  enforcer: "pemblokir",
  both: "pemblokir + pengumpul data",
  collector: "pengumpul data saja",
  none: "belum diset",
};

const fmtNum = (v, digits = 2) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)}G`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Number(n.toFixed(digits)));
};

const fmtTime = (v) => (v ? String(v).slice(0, 19).replace("T", " ") : "-");

const asText = (value) => (Array.isArray(value) ? value.join(", ") : String(value ?? ""));

const parseField = (field, raw, sample) => {
  if (typeof sample === "boolean") return !!raw;
  if (Array.isArray(sample)) {
    const parts = String(raw || "").split(/[\s,]+/).map((p) => p.trim()).filter(Boolean);
    if (!parts.length) throw new Error("daftar tidak boleh kosong");
    return parts.map((p) => {
      const n = Number(p);
      if (!Number.isFinite(n)) throw new Error(`'${p}' bukan angka`);
      return n;
    });
  }
  if (Number.isInteger(sample)) {
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0) throw new Error("harus angka >= 0");
    return Math.round(n);
  }
  if (typeof sample === "number") {
    const n = Number(raw);
    if (!Number.isFinite(n) || n < 0) throw new Error("harus angka >= 0");
    return n;
  }
  return raw;
};

const Section = ({ title, hint, children, right }) => (
  <Card className="overflow-hidden mb-6">
    <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="text-xs font-bold uppercase tracking-widest text-slate-600">{title}</div>
        {hint && <div className="text-xs text-slate-500 mt-0.5 max-w-3xl">{hint}</div>}
      </div>
      {right}
    </div>
    <div className="p-5">{children}</div>
  </Card>
);

export const OutboundAbuse = () => {
  const [cfgResp, setCfgResp] = useState(null);
  const [form, setForm] = useState(null);
  const [savingCfg, setSavingCfg] = useState(false);
  const [msg, setMsg] = useState(null);

  const [summary, setSummary] = useState(null);
  const [shadow, setShadow] = useState([]);
  const [expanded, setExpanded] = useState("");
  const [enforcers, setEnforcers] = useState(null);

  const [modeInput, setModeInput] = useState("");
  const [modeBusy, setModeBusy] = useState(false);

  const [resolveIp, setResolveIp] = useState("");
  const [resolveOut, setResolveOut] = useState(null);
  const [resolveBusy, setResolveBusy] = useState(false);

  const [liftIp, setLiftIp] = useState("");
  const [liftOut, setLiftOut] = useState(null);
  const [liftBusy, setLiftBusy] = useState(false);

  const [ovForm, setOvForm] = useState({ target: "", field: "dst_diversity_min", value: "", hours: "", reason: "" });
  const [ovBusy, setOvBusy] = useState(false);
  const [ovErr, setOvErr] = useState("");

  const loadConfig = useCallback(() => api.get("/admin/noc/outbound/config")
    .then((r) => {
      setCfgResp(r.data);
      const next = {};
      Object.entries(r.data.config || {}).forEach(([k, v]) => { next[k] = asText(v); });
      next.enabled = !!(r.data.config || {}).enabled;
      setForm(next);
    })
    .catch((e) => setMsg({ ok: false, text: formatApiError(e) || "Gagal memuat konfigurasi" })), []);

  const loadSummary = useCallback(() => api.get("/admin/noc/outbound/summary", { params: { hours: 24 } })
    .then((r) => setSummary(r.data)).catch(() => setSummary(null)), []);

  const loadShadow = useCallback(() => api.get("/admin/noc/outbound/shadow", { params: { limit: 60 } })
    .then((r) => setShadow(r.data.items || [])).catch(() => setShadow([])), []);

  const loadEnforcers = useCallback(() => api.get("/admin/noc/outbound/enforcers")
    .then((r) => setEnforcers(r.data)).catch(() => setEnforcers(null)), []);

  useEffect(() => { loadConfig(); loadSummary(); loadShadow(); loadEnforcers(); }, [loadConfig, loadSummary, loadShadow, loadEnforcers]);
  useEffect(() => {
    const t = setInterval(() => { loadSummary(); loadShadow(); }, 30000);
    return () => clearInterval(t);
  }, [loadSummary, loadShadow]);

  const defaults = cfgResp?.defaults || {};
  const mode = cfgResp?.config?.mode || "shadow";
  const dirty = useMemo(() => {
    if (!form || !cfgResp) return [];
    const eff = cfgResp.config || {};
    return Object.keys(eff).filter((k) => {
      if (k === "mode") return false;
      const a = typeof form[k] === "boolean" ? form[k] : asText(eff[k]);
      const b = typeof form[k] === "boolean" ? form[k] : asText(form[k]);
      return String(a) !== String(b);
    });
  }, [form, cfgResp]);

  const saveConfig = async () => {
    if (!form || !cfgResp) return;
    const eff = cfgResp.config || {};
    const payload = {};
    try {
      Object.keys(eff).forEach((k) => {
        if (k === "mode") return;
        payload[k] = parseField(k, form[k], eff[k]);
      });
    } catch (e) {
      setMsg({ ok: false, text: `Nilai tidak valid: ${e.message}` });
      return;
    }
    setSavingCfg(true);
    setMsg(null);
    try {
      const r = await api.put("/admin/noc/outbound/config", payload);
      const rejected = (r.data?.rejected || []).filter(Boolean);
      setMsg({
        ok: true,
        text: `Konfigurasi tersimpan (${Object.keys(r.data?.applied || {}).length} field)` +
              (rejected.length ? ` · ditolak: ${rejected.join(", ")}` : ""),
      });
      await loadConfig();
    } catch (e) {
      setMsg({ ok: false, text: formatApiError(e) || "Gagal menyimpan konfigurasi" });
    } finally { setSavingCfg(false); }
  };

  const setMode = async (next) => {
    setModeBusy(true);
    setMsg(null);
    try {
      const body = { mode: next };
      if (next === "enforce") body.confirm = modeInput.trim();
      const r = await api.post("/admin/noc/outbound/mode", body);
      setMsg({ ok: true, text: `Mode sekarang: ${r.data?.effective || next}` });
      setModeInput("");
      await loadConfig();
    } catch (e) {
      setMsg({ ok: false, text: formatApiError(e) || "Gagal mengubah mode" });
    } finally { setModeBusy(false); }
  };

  const doResolve = async () => {
    const ip = resolveIp.trim();
    if (!ip) { setResolveOut({ error: "Isi IP pelanggan dulu" }); return; }
    setResolveBusy(true);
    try {
      const r = await api.post("/admin/noc/outbound/resolve", { target: ip });
      setResolveOut(r.data);
    } catch (e) {
      setResolveOut({ error: formatApiError(e) || "Gagal menelusuri device" });
    } finally { setResolveBusy(false); }
  };

  const doLift = async () => {
    const ip = liftIp.trim();
    if (!ip) { setLiftOut({ error: "Isi IP yang mau dicabut" }); return; }
    setLiftBusy(true);
    setLiftOut(null);
    try {
      const r = await api.post("/admin/noc/outbound/lift", { target: ip });
      setLiftOut(r.data);
      await loadShadow();
    } catch (e) {
      setLiftOut({ error: formatApiError(e) || "Gagal mencabut blokir" });
    } finally { setLiftBusy(false); }
  };

  const createOverride = async () => {
    setOvErr("");
    const target = ovForm.target.trim();
    const value = ovForm.value.trim();
    if (!target) { setOvErr("IP target wajib diisi"); return; }
    if (!value) { setOvErr("Nilai override wajib diisi"); return; }
    setOvBusy(true);
    try {
      const sample = defaults[ovForm.field];
      const body = {
        target,
        field: ovForm.field,
        value: Array.isArray(sample)
          ? value.split(/[\s,]+/).filter(Boolean).map(Number)
          : (Number.isFinite(Number(value)) ? Number(value) : value),
        reason: ovForm.reason,
      };
      if (ovForm.hours.trim()) body.hours = Number(ovForm.hours);
      await api.post("/admin/noc/outbound/overrides", body);
      setOvForm({ target: "", field: ovForm.field, value: "", hours: "", reason: "" });
      setMsg({ ok: true, text: `Override dibuat untuk ${target}` });
    } catch (e) {
      setOvErr(formatApiError(e) || "Gagal membuat override");
    } finally { setOvBusy(false); }
  };

  const renderField = (key) => {
    const sample = cfgResp?.config?.[key];
    const def = defaults?.[key];
    const isBool = typeof sample === "boolean";
    const isList = Array.isArray(sample);
    const changed = defaults && String(asText(def)) !== String(asText(form?.[key]));
    return (
      <div key={key} className="min-w-0">
        <label className={`${labelClass} block mb-1`} htmlFor={`ob-${key}`}>
          {LABELS[key] || key}
          {changed && <span className="ml-2 text-[10px] font-bold text-amber-600 normal-case">diubah</span>}
        </label>
        {isBool ? (
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              id={`ob-${key}`}
              type="checkbox"
              className="h-4 w-4"
              checked={!!form?.[key]}
              onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.checked }))}
              data-testid={`outbound-field-${key}`}
            />
            {form?.[key] ? "aktif" : "nonaktif"}
          </label>
        ) : (
          <input
            id={`ob-${key}`}
            className={inputClass}
            value={form?.[key] ?? ""}
            onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
            inputMode={isList ? "text" : "decimal"}
            data-testid={`outbound-field-${key}`}
          />
        )}
        <div className="text-[10px] text-slate-400 mt-1 font-mono">
          default: {asText(def)}{isList ? " (pisahkan dengan koma)" : ""}
        </div>
        {RATIO_FIELDS.has(key) && Number(form?.[key]) > 1 && (
          <div className="text-[11px] text-red-600 mt-1 font-semibold" data-testid={`outbound-warn-${key}`}>
            Nilai ini harus desimal 0–1. Untuk 60% tulis 0.6, bukan 60.
          </div>
        )}
        {HELP[key] && (
          <div className="text-[11px] text-slate-500 mt-1 leading-snug">{HELP[key]}</div>
        )}
      </div>
    );
  };

  return (
    <div data-testid="outbound-abuse">
      <Section
        title="Mitigasi serangan keluar (outbound abuse)"
        hint="Kalau pelanggan kita menyerang internet luar, yang diblokir adalah IP pelanggan itu sendiri — bukan tujuan serangannya, karena memblokir tujuan akan memutus akses pelanggan lain. Penilaian memakai bentuk paket, bukan besarnya bandwidth, supaya pelanggan 1 Gbps dan uplink 200 Mbps dinilai dengan ukuran yang adil."
        right={(
          <div className="flex items-center gap-2">
            <span className={`px-2 py-1 rounded-full border text-[10px] font-bold uppercase ${
              mode === "enforce"
                ? "bg-red-100 text-red-700 border-red-300"
                : "bg-amber-100 text-amber-800 border-amber-300"}`} data-testid="outbound-mode-badge">
              {mode === "enforce" ? "sedang memblokir" : "hanya menguji"}
            </span>
            <button className={btnSecondary} onClick={() => { loadConfig(); loadSummary(); loadShadow(); loadEnforcers(); }}>
              <Activity className="h-4 w-4" /> Muat ulang
            </button>
          </div>
        )}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          {[
            ["Pengamatan 24 jam terakhir", summary ? summary.scored_windows : "-"],
            ["Yang akan diblokir", summary ? summary.would_block : "-"],
            ["Bagian yang diblokir", summary ? `${((summary.rate || 0) * 100).toFixed(2)}%` : "-"],
            ["Perangkat siap memblokir", enforcers ? enforcers.enforcers : "-"],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
              <div className="text-lg font-bold text-[#0a2350] tabular-nums">{value}</div>
            </div>
          ))}
        </div>

        {msg && (
          <div className={`mb-4 flex items-start gap-2 text-sm ${msg.ok ? "text-emerald-700" : "text-red-700"}`} data-testid="outbound-msg">
            {msg.ok ? <CheckCircle2 className="h-4 w-4 mt-0.5" /> : <XCircle className="h-4 w-4 mt-0.5" />}
            <span>{msg.text}</span>
          </div>
        )}

        <div className="rounded-lg border border-slate-200 p-4">
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 mb-1">Pilih cara kerja</div>
          <div className="text-xs text-slate-500 mb-3 space-y-1">
            <div>
              <b>Uji dulu (shadow)</b> — sistem mencatat keputusan dan menampilkannya di tabel
              "Keputusan terakhir", tetapi <b>tidak ada satu paket pun yang dijatuhkan</b>.
              Pakai mode ini untuk melihat apakah ambang sudah masuk akal.
            </div>
            <div>
              <b>Blokir sungguhan (enforce)</b> — IP pelanggan yang dinilai menyerang benar-benar
              diputus dengan menuliskannya ke router. Untuk masuk mode ini harus ada minimal satu
              perangkat yang ditunjuk sebagai pemblokir, dan Anda harus mengetik ENFORCE sebagai konfirmasi.
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <button
              className={btnSecondary}
              disabled={modeBusy || mode === "shadow"}
              onClick={() => setMode("shadow")}
              data-testid="outbound-mode-shadow"
            >
              {modeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldOff className="h-4 w-4" />} Kembali ke uji saja
            </button>
            <div className="min-w-[200px]">
              <label className={`${labelClass} block mb-1`} htmlFor="ob-confirm">Ketik ENFORCE</label>
              <input
                id="ob-confirm"
                className={inputClass}
                value={modeInput}
                onChange={(e) => setModeInput(e.target.value)}
                placeholder="ENFORCE"
                data-testid="outbound-mode-confirm"
              />
            </div>
            <button
              className={btnDanger}
              disabled={modeBusy || modeInput.trim() !== "ENFORCE" || mode === "enforce"}
              onClick={() => setMode("enforce")}
              data-testid="outbound-mode-enforce"
            >
              {modeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />} Mulai blokir sungguhan
            </button>
          </div>
        </div>
      </Section>

      <Section
        title="Ambang deteksi"
        hint="Angka-angka di bawah ini menentukan kapan trafik dianggap serangan. Semuanya bisa diubah tanpa deploy — begitu disimpan, pemantauan (yang berjalan tiap 10 detik) langsung memakai nilai baru. Tiap kolom punya penjelasan singkat di bawahnya; baca itu sebelum mengubah angka."
        right={(
          <div className="flex items-center gap-2">
            {dirty.length > 0 && (
              <span className="text-[11px] font-semibold text-amber-700" data-testid="outbound-dirty">
                {dirty.length} kolom belum disimpan
              </span>
            )}
            <button className={btnPrimary} onClick={saveConfig} disabled={savingCfg || !form} data-testid="outbound-save-config">
              {savingCfg ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Simpan
            </button>
          </div>
        )}
      >
        {!form && <div className="text-sm text-slate-500">Memuat konfigurasi...</div>}
        {form && GROUPS.map((g) => (
          <div key={g.key} className="mb-5 last:mb-0">
            <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350] mb-0.5">{g.title}</div>
            <div className="text-[11px] text-slate-500 mb-2">{g.hint}</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-3">
              {g.fields.map(renderField)}
            </div>
          </div>
        ))}
      </Section>

      <Section
        title="Perangkat mana yang menjalankan blokir"
        hint="Kalau satu IP pelanggan harus diblokir, sistem memilih router yang paling dekat dengan pelanggan tersebut. Router yang sudah ditetapkan untuk site tertentu selalu didahulukan. Kalau tidak ada, dipilih router dengan alamat jaringan paling spesifik, lalu prioritas tertinggi."
        right={(
          <span className="text-[11px] text-slate-500">
            {enforcers ? `${enforcers.enforcers} perangkat ditunjuk · ${enforcers.prefix_count} jaringan terdaftar` : "-"}
          </span>
        )}
      >
        {!enforcers && <div className="text-sm text-slate-500">Memuat perangkat...</div>}
        {enforcers && enforcers.devices.length === 0 && (
          <div className="text-sm text-slate-500">Belum ada perangkat MikroTik yang terdaftar.</div>
        )}
        {enforcers && enforcers.devices.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-3">Perangkat</th>
                  <th className="py-2 pr-3">Alamat</th>
                  <th className="py-2 pr-3">Peran</th>
                  <th className="py-2 pr-3">Dipakai untuk site</th>
                  <th className="py-2 pr-3">Jumlah jaringan</th>
                  <th className="py-2 pr-3">Urutan prioritas</th>
                  <th className="py-2">Boleh memblokir</th>
                </tr>
              </thead>
              <tbody>
                {enforcers.devices.map((d) => (
                  <tr key={d.id || d.host} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-3 font-semibold text-[#0a2350]">{d.name || "-"}</td>
                    <td className="py-2 pr-3 font-mono text-[12px]">{d.host || "-"}</td>
                    <td className="py-2 pr-3">
                      <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${ROLE_BADGE[d.role] || ROLE_BADGE.none}`}>
                        {ROLE_LABEL[d.role] || d.role}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-[12px] text-slate-600">
                      {Array.isArray(d.sites) && d.sites.length ? d.sites.join(", ") : <span className="text-slate-400">semua site</span>}
                    </td>
                    <td className="py-2 pr-3 tabular-nums">{d.coverage_count}</td>
                    <td className="py-2 pr-3 tabular-nums">{d.priority}</td>
                    <td className="py-2">
                      {d.can_enforce
                        ? <span className="text-emerald-600 font-semibold inline-flex items-center gap-1"><CheckCircle2 className="h-3.5 w-3.5" /> ya</span>
                        : <span className="text-slate-400 inline-flex items-center gap-1"><XCircle className="h-3.5 w-3.5" /> tidak</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="mt-4 pt-4 border-t border-slate-100">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-600 mb-2">
            Cek: IP ini akan diblokir lewat perangkat mana?
          </div>
          <div className="text-[12px] text-slate-500 mb-2">
            Masukkan IP pelanggan untuk melihat router mana yang akan dipakai, dan alasannya.
            Berguna sebelum mengaktifkan mode blokir sungguhan.
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              className={`${inputClass} max-w-[240px]`}
              value={resolveIp}
              onChange={(e) => setResolveIp(e.target.value)}
              placeholder="157.20.32.166"
              data-testid="outbound-resolve-input"
            />
            <button className={btnSecondary} onClick={doResolve} disabled={resolveBusy} data-testid="outbound-resolve-run">
              {resolveBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Cek
            </button>
          </div>
          {resolveOut && resolveOut.error && <div className="text-sm text-red-700 mt-2">{resolveOut.error}</div>}
          {resolveOut && !resolveOut.error && (
            <div className="mt-2 text-sm text-slate-700" data-testid="outbound-resolve-result">
              <div className="text-[12px] text-slate-500 mb-1">
                {resolveOut.customer || "pelanggan tidak dikenal"} · jaringan {resolveOut.prefix || "-"} · site {resolveOut.site || "-"}
              </div>
              {(resolveOut.order || []).length === 0 && <div className="text-amber-700">Tidak ada perangkat yang bisa memblokir IP ini.</div>}
              <ol className="list-decimal ml-5 space-y-0.5">
                {(resolveOut.order || []).map((o, i) => (
                  <li key={`${o.host}-${i}`}>
                    <b>{o.device}</b> <span className="font-mono text-[12px] text-slate-500">{o.host}</span>
                    <span className="text-[11px] text-slate-500"> — {o.reason}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </Section>

      <Section
        title="Catatan keputusan"
        hint="Ini riwayat penilaian sistem. Satu baris = satu kali pengamatan. Kolom Keputusan menunjukkan apa yang AKAN dilakukan: 'diblokir' berarti di mode uji hanya tercatat, di mode blokir sungguhan IP-nya benar-benar diputus. Klik tanda panah untuk melihat alasan lengkapnya."
        right={(
          <button className={btnSecondary} onClick={loadShadow}>
            <Activity className="h-4 w-4" /> Segarkan
          </button>
        )}
      >
        {shadow.length === 0 && <div className="text-sm text-slate-500">Belum ada pengamatan yang mencurigakan.</div>}
        {shadow.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-2"> </th>
                  <th className="py-2 pr-3">Waktu (UTC)</th>
                  <th className="py-2 pr-3">IP pelanggan</th>
                  <th className="py-2 pr-3">Poin</th>
                  <th className="py-2 pr-3">Ciri terpenuhi</th>
                  <th className="py-2 pr-3">Paket/detik</th>
                  <th className="py-2 pr-3">Lama pantau</th>
                  <th className="py-2 pr-3">Porsi minta-konek</th>
                  <th className="py-2 pr-3">Porsi paket kecil</th>
                  <th className="py-2 pr-3">Jumlah tujuan</th>
                  <th className="py-2">Keputusan</th>
                </tr>
              </thead>
              <tbody>
                {shadow.map((row) => {
                  const m = row.metrics || {};
                  const sig = row.signals || {};
                  const on = Object.keys(SIGNAL_LABELS).filter((k) => sig[k]);
                  const open = expanded === row.id;
                  return (
                    <React.Fragment key={row.id}>
                      <tr className="border-b border-slate-100 last:border-0">
                        <td className="py-2 pr-2">
                          <button className="text-slate-400 hover:text-[#0a2350]" onClick={() => setExpanded(open ? "" : row.id)}>
                            {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </button>
                        </td>
                        <td className="py-2 pr-3 text-[12px] text-slate-500 tabular-nums">{fmtTime(row.at)}</td>
                        <td className="py-2 pr-3 font-mono font-semibold text-[#0a2350]">{row.target}</td>
                        <td className="py-2 pr-3 tabular-nums font-bold">{row.score}</td>
                        <td className="py-2 pr-3">
                          <div className="flex flex-wrap gap-1">
                            {on.length === 0 && <span className="text-slate-400 text-[11px]">-</span>}
                            {on.map((k) => (
                              <span key={k} className="px-1.5 py-0.5 rounded border border-amber-300 bg-amber-50 text-amber-800 text-[10px] font-bold">
                                {k.slice(0, 2)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 pr-3 tabular-nums">{fmtNum(m.pps)}</td>
                        <td className="py-2 pr-3 tabular-nums text-[12px]">
                          {m.window_s != null ? `${Number(m.window_s).toFixed(1)}s` : "-"}
                          {row.authoritative === false && (
                            <span
                              className="ml-1 px-1 py-0.5 rounded border border-amber-300 bg-amber-50 text-amber-800 text-[9px] font-bold uppercase"
                              title="Pengamatan ini tidak mewakili seluruh trafik: persentase di baris ini bisa lebih tinggi dari yang sebenarnya"
                            >
                              ?
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-3 tabular-nums">{m.syn_share != null ? `${(Number(m.syn_share) * 100).toFixed(0)}%` : "-"}</td>
                        <td className="py-2 pr-3 tabular-nums">{m.small_share != null ? `${(Number(m.small_share) * 100).toFixed(0)}%` : "-"}</td>
                        <td className="py-2 pr-3 tabular-nums">{m.dst_diversity ?? "-"}</td>
                        <td className="py-2">
                          {row.would_block
                            ? <span className="px-2 py-0.5 rounded-full border border-red-300 bg-red-100 text-red-700 text-[10px] font-bold uppercase">diblokir</span>
                            : <span className="px-2 py-0.5 rounded-full border border-slate-300 bg-slate-100 text-slate-600 text-[10px] font-bold uppercase">dilewatkan</span>}
                        </td>
                      </tr>
                      {open && (
                        <tr className="bg-slate-50">
                          <td />
                          <td colSpan={10} className="py-2 pr-3">
                            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-1">
                              Mengapa diputuskan begitu
                            </div>
                            <div className="text-[12px] text-slate-700 font-mono break-all bg-white border border-slate-200 rounded px-2 py-1">
                              {(row.reason || "-")}
                            </div>
                            <div className="text-[11px] text-slate-600 mt-2">
                              <b>Ciri serangan:</b>{" "}
                              {Object.keys(SIGNAL_LABELS).map((k) => `${SIGNAL_LABELS[k]}: ${sig[k] ? "ya" : "tidak"}`).join(" · ")}
                            </div>
                            <div className="text-[11px] text-slate-500 mt-1">
                              <b>Angka pendukung:</b> permintaan konek dibalas {m.synack_packets ?? "-"} ·
                              perbandingan minta:balas {m.fanout_ratio ?? "-"} ·
                              laju data {fmtNum(m.bytes_per_s)} byte/detik ·
                              jumlah alur {m.flow_count ?? "-"}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section
        title="Pengecualian per pelanggan"
        hint="Ini DAFTAR PUTIH, bukan daftar hitam. Gunakan untuk pelanggan yang trafiknya mirip serangan padahal sah — misalnya scanner internal, server backup, atau transfer besar yang sudah disetujui. Pelanggan yang ada di sini tidak akan diblokir otomatis, meskipun bentuk trafiknya mencurigakan."
      >
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 mb-4 text-[12px] text-amber-900">
          <b>Cara pakai:</b> masukkan IP pelanggan, pilih pengaturan mana yang ingin dilonggarkan,
          isi nilai barunya, lalu tentukan berapa lama berlaku. Kosongkan kolom jam kalau ingin
          berlaku terus sampai dihapus.
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end">
          <div>
            <label className={`${labelClass} block mb-1`}>IP pelanggan yang dikecualikan</label>
            <input className={inputClass} value={ovForm.target}
                   onChange={(e) => setOvForm((f) => ({ ...f, target: e.target.value }))}
                   placeholder="157.20.32.166" data-testid="outbound-override-target" />
          </div>
          <div>
            <label className={`${labelClass} block mb-1`}>Pengaturan yang dilonggarkan</label>
            <select className={inputClass} value={ovForm.field}
                    onChange={(e) => setOvForm((f) => ({ ...f, field: e.target.value }))}
                    data-testid="outbound-override-field">
              {Object.keys(LABELS).filter((k) => !["enabled", "mode"].includes(k)).map((k) => (
                <option key={k} value={k}>{LABELS[k]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={`${labelClass} block mb-1`}>Nilai khusus untuk IP ini</label>
            <input className={inputClass} value={ovForm.value}
                   onChange={(e) => setOvForm((f) => ({ ...f, value: e.target.value }))}
                   placeholder={`contoh: ${asText(defaults[ovForm.field])}`} data-testid="outbound-override-value" />
          </div>
          <div>
            <label className={`${labelClass} block mb-1`}>Berlaku berapa jam</label>
            <input className={inputClass} value={ovForm.hours}
                   onChange={(e) => setOvForm((f) => ({ ...f, hours: e.target.value }))}
                   placeholder="kosong = selamanya" data-testid="outbound-override-hours" />
          </div>
          <button className={btnSecondary} onClick={createOverride} disabled={ovBusy} data-testid="outbound-override-create">
            {ovBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />} Kecualikan
          </button>
        </div>
        <div className="mt-2">
          <input className={inputClass} value={ovForm.reason}
                 onChange={(e) => setOvForm((f) => ({ ...f, reason: e.target.value }))}
                 placeholder="Alasan — wajib diisi supaya rekan lain tahu kenapa IP ini dikecualikan" data-testid="outbound-override-reason" />
        </div>
        {ovErr && <div className="text-sm text-red-700 mt-2">{ovErr}</div>}
      </Section>

      <Section
        title="Cabut blokir"
        hint="Dipakai kalau ada pelanggan yang terblokir padahal sebenarnya tidak menyerang. Masukkan IP-nya di sini; sistem menghapus blokir dari router yang bersangkutan lalu memeriksa ulang apakah benar-benar sudah hilang. Kalau hasilnya 'belum terverifikasi', artinya router tidak menjawab — perlu dicek manual."
      >
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${inputClass} max-w-[240px]`} value={liftIp}
                 onChange={(e) => setLiftIp(e.target.value)}
                 placeholder="IP pelanggan yang terblokir" data-testid="outbound-lift-input" />
          <button className={btnSecondary} onClick={doLift} disabled={liftBusy} data-testid="outbound-lift-run">
            {liftBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />} Cabut blokir
          </button>
        </div>
        {liftOut && liftOut.error && <div className="text-sm text-red-700 mt-2">{liftOut.error}</div>}
        {liftOut && !liftOut.error && (
          <div className="mt-2 text-sm" data-testid="outbound-lift-result">
            <div className={liftOut.ok ? "text-emerald-700" : "text-amber-700"}>
              {liftOut.ok ? "Blokir sudah dicabut dan sudah dipastikan hilang." : "Belum bisa dipastikan tercabut — perlu dicek langsung di router."}
            </div>
            <ul className="mt-1 text-[12px] text-slate-600 font-mono">
              {(liftOut.attempts || []).map((a, i) => (
                <li key={`${a.device}-${i}`}>
                  {a.device}: {a.ok ? `${a.removed} entri dihapus` : a.error || "gagal"}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>
    </div>
  );
};

export default OutboundAbuse;
