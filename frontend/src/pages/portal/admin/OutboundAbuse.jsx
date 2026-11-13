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
const GROUPS = [
  {
    key: "gate",
    title: "Gerbang volume",
    hint: "Hanya menyaring target sepi. Tidak pernah ikut menentukan blokir.",
    fields: ["enabled", "window_seconds", "skip_below_pps", "skip_below_bytes", "small_packet_bytes"],
  },
  {
    key: "shape",
    title: "Sinyal bentuk trafik",
    hint: "Bukti serangan sesungguhnya: SYN, diversitas tujuan, paket kecil, tidak ada balasan.",
    fields: ["syn_pps_min", "syn_ratio_min", "dst_diversity_min", "small_pps_min",
             "small_packet_ratio_min", "fanout_min_syn", "fanout_ratio_min"],
  },
  {
    key: "decision",
    title: "Aturan keputusan",
    hint: "Kapan skor berubah menjadi blokir. Naikkan bila masih ada false positive.",
    fields: ["min_score_to_block", "min_signals_to_block", "confirm_windows",
             "instant_critical_pps", "instant_critical_syn_ratio"],
  },
  {
    key: "penalty",
    title: "Hukuman berjenjang",
    hint: "Pelanggaran berulang mendapat durasi lebih panjang. -1 = permanen sampai dicabut manual.",
    fields: ["penalty_ladder_hours", "penalty_memory_days"],
  },
];

const LABELS = {
  enabled: "Aktifkan deteksi outbound",
  window_seconds: "Panjang window (detik)",
  skip_below_pps: "Gerbang minimum (pps)",
  skip_below_bytes: "Gerbang minimum (byte / window)",
  small_packet_bytes: "Ambang paket kecil (byte)",
  syn_pps_min: "SYN per detik minimum",
  syn_ratio_min: "Porsi SYN minimum",
  dst_diversity_min: "Jumlah host tujuan berbeda",
  small_pps_min: "Pps paket kecil minimum",
  small_packet_ratio_min: "Porsi paket kecil minimum",
  fanout_min_syn: "SYN minimum sebelum cek balasan",
  fanout_ratio_min: "Rasio SYN : SYN-ACK minimum",
  min_score_to_block: "Skor minimum untuk blokir",
  min_signals_to_block: "Sinyal bentuk minimum",
  confirm_windows: "Window berturut-turut",
  instant_critical_pps: "Pps kritis (blokir langsung)",
  instant_critical_syn_ratio: "Porsi SYN kritis",
  penalty_ladder_hours: "Tangga hukuman (jam)",
  penalty_memory_days: "Memori pelanggaran (hari)",
};

const SIGNAL_LABELS = {
  S1_syn_flood: "S1 SYN flood",
  S2_dst_fanout: "S2 fanout tujuan",
  S3_small_packets: "S3 paket kecil",
  S4_no_return: "S4 tanpa balasan",
  S5_persistence: "S5 persisten",
};

const ROLE_BADGE = {
  enforcer: "bg-emerald-100 text-emerald-700 border-emerald-300",
  both: "bg-emerald-100 text-emerald-700 border-emerald-300",
  collector: "bg-blue-100 text-blue-700 border-blue-300",
  none: "bg-slate-100 text-slate-600 border-slate-300",
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
      </div>
    );
  };

  return (
    <div data-testid="outbound-abuse">
      <Section
        title="Mitigasi serangan keluar (outbound abuse)"
        hint="Deteksi memakai bentuk trafik, bukan besar bandwidth: pelanggan flagship 1 Gbps dan uplink interkoneksi 200 Mbps tidak boleh dinilai dengan angka yang sama."
        right={(
          <div className="flex items-center gap-2">
            <span className={`px-2 py-1 rounded-full border text-[10px] font-bold uppercase ${
              mode === "enforce"
                ? "bg-red-100 text-red-700 border-red-300"
                : "bg-amber-100 text-amber-800 border-amber-300"}`} data-testid="outbound-mode-badge">
              mode: {mode}
            </span>
            <button className={btnSecondary} onClick={() => { loadConfig(); loadSummary(); loadShadow(); loadEnforcers(); }}>
              <Activity className="h-4 w-4" /> Muat ulang
            </button>
          </div>
        )}
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          {[
            ["Window dinilai (24j)", summary ? summary.scored_windows : "-"],
            ["Akan diblokir (24j)", summary ? summary.would_block : "-"],
            ["Rasio blokir", summary ? `${((summary.rate || 0) * 100).toFixed(2)}%` : "-"],
            ["Device penegak", enforcers ? enforcers.enforcers : "-"],
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
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 mb-1">Mode kerja</div>
          <div className="text-xs text-slate-500 mb-3">
            <b>shadow</b> hanya mencatat keputusan. <b>enforce</b> benar-benar menulis blokir /32 ke router.
            Mode enforce menuntut minimal satu device dengan peran <code>enforcer</code> dan konfirmasi ketik ENFORCE.
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <button
              className={btnSecondary}
              disabled={modeBusy || mode === "shadow"}
              onClick={() => setMode("shadow")}
              data-testid="outbound-mode-shadow"
            >
              {modeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldOff className="h-4 w-4" />} Ke shadow
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
              {modeBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />} Aktifkan enforce
            </button>
          </div>
        </div>
      </Section>

      <Section
        title="Ambang deteksi"
        hint="Semua nilai di sini tersimpan di database dan dibaca ulang oleh sweep setiap 10 detik. Tidak ada yang di-hardcode."
        right={(
          <div className="flex items-center gap-2">
            {dirty.length > 0 && (
              <span className="text-[11px] font-semibold text-amber-700" data-testid="outbound-dirty">
                {dirty.length} field belum disimpan
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
        title="Device penegak & cakupan"
        hint="Device dengan sites[] eksplisit selalu mengalahkan catch-all. Urutan percobaan: scoped dulu, lalu prefix paling spesifik, lalu priority, lalu host."
        right={(
          <span className="text-[11px] text-slate-500">
            {enforcers ? `${enforcers.enforcers} penegak · ${enforcers.prefix_count} prefix DCIM` : "-"}
          </span>
        )}
      >
        {!enforcers && <div className="text-sm text-slate-500">Memuat device...</div>}
        {enforcers && enforcers.devices.length === 0 && (
          <div className="text-sm text-slate-500">Belum ada device MikroTik terdaftar.</div>
        )}
        {enforcers && enforcers.devices.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-3">Device</th>
                  <th className="py-2 pr-3">Host</th>
                  <th className="py-2 pr-3">Peran</th>
                  <th className="py-2 pr-3">Sites</th>
                  <th className="py-2 pr-3">Coverage</th>
                  <th className="py-2 pr-3">Priority</th>
                  <th className="py-2">Bisa menegakkan</th>
                </tr>
              </thead>
              <tbody>
                {enforcers.devices.map((d) => (
                  <tr key={d.id || d.host} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-3 font-semibold text-[#0a2350]">{d.name || "-"}</td>
                    <td className="py-2 pr-3 font-mono text-[12px]">{d.host || "-"}</td>
                    <td className="py-2 pr-3">
                      <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${ROLE_BADGE[d.role] || ROLE_BADGE.none}`}>
                        {d.role}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-[12px] text-slate-600">
                      {Array.isArray(d.sites) && d.sites.length ? d.sites.join(", ") : <span className="text-slate-400">catch-all</span>}
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
            Telusuri: IP ini akan ditangani device mana
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
              {resolveBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Telusuri
            </button>
          </div>
          {resolveOut && resolveOut.error && <div className="text-sm text-red-700 mt-2">{resolveOut.error}</div>}
          {resolveOut && !resolveOut.error && (
            <div className="mt-2 text-sm text-slate-700" data-testid="outbound-resolve-result">
              <div className="text-[12px] text-slate-500 mb-1">
                {resolveOut.customer || "pelanggan tidak dikenal"} · prefix {resolveOut.prefix || "-"} · site {resolveOut.site || "-"}
              </div>
              {(resolveOut.order || []).length === 0 && <div className="text-amber-700">Tidak ada device yang bisa menegakkan IP ini.</div>}
              <ol className="list-decimal ml-5 space-y-0.5">
                {(resolveOut.order || []).map((o, i) => (
                  <li key={`${o.host}-${i}`}>
                    <b>{o.device}</b> <span className="font-mono text-[12px] text-slate-500">{o.host}</span>
                    <span className="text-[11px] text-slate-500"> — {o.reason} (prefix {o.matched_prefix || "-"}, spesifisitas {o.specificity})</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      </Section>

      <Section
        title="Keputusan terakhir (shadow)"
        hint="Setiap baris adalah satu window yang punya sinyal. Selama mode shadow, tidak ada paket yang dijatuhkan."
        right={(
          <button className={btnSecondary} onClick={loadShadow}>
            <Activity className="h-4 w-4" /> Segarkan
          </button>
        )}
      >
        {shadow.length === 0 && <div className="text-sm text-slate-500">Belum ada window bersinyal.</div>}
        {shadow.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-200">
                  <th className="py-2 pr-2"> </th>
                  <th className="py-2 pr-3">Waktu (UTC)</th>
                  <th className="py-2 pr-3">Sumber</th>
                  <th className="py-2 pr-3">Skor</th>
                  <th className="py-2 pr-3">Sinyal</th>
                  <th className="py-2 pr-3">Pps</th>
                  <th className="py-2 pr-3">SYN</th>
                  <th className="py-2 pr-3">Kecil</th>
                  <th className="py-2 pr-3">Tujuan</th>
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
                        <td className="py-2 pr-3 tabular-nums">{m.syn_share != null ? `${(Number(m.syn_share) * 100).toFixed(0)}%` : "-"}</td>
                        <td className="py-2 pr-3 tabular-nums">{m.small_share != null ? `${(Number(m.small_share) * 100).toFixed(0)}%` : "-"}</td>
                        <td className="py-2 pr-3 tabular-nums">{m.dst_diversity ?? "-"}</td>
                        <td className="py-2">
                          {row.would_block
                            ? <span className="px-2 py-0.5 rounded-full border border-red-300 bg-red-100 text-red-700 text-[10px] font-bold uppercase">blokir</span>
                            : <span className="px-2 py-0.5 rounded-full border border-slate-300 bg-slate-100 text-slate-600 text-[10px] font-bold uppercase">lewat</span>}
                        </td>
                      </tr>
                      {open && (
                        <tr className="bg-slate-50">
                          <td />
                          <td colSpan={9} className="py-2 pr-3">
                            <div className="text-[12px] text-slate-600 font-mono break-all">
                              {(row.reason || "-")}
                            </div>
                            <div className="text-[11px] text-slate-500 mt-1">
                              {Object.keys(SIGNAL_LABELS).map((k) => `${SIGNAL_LABELS[k]}: ${sig[k] ? "ya" : "tidak"}`).join(" · ")}
                            </div>
                            <div className="text-[11px] text-slate-500 mt-1 font-mono">
                              fanout SYN:SYN-ACK = {m.fanout_ratio ?? "-"} · balasan = {m.synack_packets ?? "-"} · byte/s = {fmtNum(m.bytes_per_s)} · flows = {m.flow_count ?? "-"}
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
        title="Override per pelanggan"
        hint="Untuk pelanggan sah yang bentuk trafiknya mirip serangan (scanner internal, bulk transfer disetujui). Berlaku per IP, dengan masa berlaku opsional."
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end">
          <div>
            <label className={`${labelClass} block mb-1`}>IP pelanggan</label>
            <input className={inputClass} value={ovForm.target}
                   onChange={(e) => setOvForm((f) => ({ ...f, target: e.target.value }))}
                   placeholder="157.20.32.166" data-testid="outbound-override-target" />
          </div>
          <div>
            <label className={`${labelClass} block mb-1`}>Field</label>
            <select className={inputClass} value={ovForm.field}
                    onChange={(e) => setOvForm((f) => ({ ...f, field: e.target.value }))}
                    data-testid="outbound-override-field">
              {Object.keys(LABELS).filter((k) => !["enabled", "mode"].includes(k)).map((k) => (
                <option key={k} value={k}>{LABELS[k]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={`${labelClass} block mb-1`}>Nilai</label>
            <input className={inputClass} value={ovForm.value}
                   onChange={(e) => setOvForm((f) => ({ ...f, value: e.target.value }))}
                   placeholder={asText(defaults[ovForm.field])} data-testid="outbound-override-value" />
          </div>
          <div>
            <label className={`${labelClass} block mb-1`}>Berlaku (jam)</label>
            <input className={inputClass} value={ovForm.hours}
                   onChange={(e) => setOvForm((f) => ({ ...f, hours: e.target.value }))}
                   placeholder="kosong = permanen" data-testid="outbound-override-hours" />
          </div>
          <button className={btnSecondary} onClick={createOverride} disabled={ovBusy} data-testid="outbound-override-create">
            {ovBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Network className="h-4 w-4" />} Tambah
          </button>
        </div>
        <div className="mt-2">
          <input className={inputClass} value={ovForm.reason}
                 onChange={(e) => setOvForm((f) => ({ ...f, reason: e.target.value }))}
                 placeholder="Alasan (muncul di audit log)" data-testid="outbound-override-reason" />
        </div>
        {ovErr && <div className="text-sm text-red-700 mt-2">{ovErr}</div>}
      </Section>

      <Section
        title="Cabut blokir"
        hint="Menghapus entri address-list portal-srcblock dari router yang menegakkan IP tersebut, lalu memverifikasi hasilnya lewat print ulang."
      >
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${inputClass} max-w-[240px]`} value={liftIp}
                 onChange={(e) => setLiftIp(e.target.value)}
                 placeholder="IP yang diblokir" data-testid="outbound-lift-input" />
          <button className={btnSecondary} onClick={doLift} disabled={liftBusy} data-testid="outbound-lift-run">
            {liftBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Undo2 className="h-4 w-4" />} Cabut blokir
          </button>
        </div>
        {liftOut && liftOut.error && <div className="text-sm text-red-700 mt-2">{liftOut.error}</div>}
        {liftOut && !liftOut.error && (
          <div className="mt-2 text-sm" data-testid="outbound-lift-result">
            <div className={liftOut.ok ? "text-emerald-700" : "text-amber-700"}>
              {liftOut.ok ? "Blokir tercabut dan terverifikasi." : "Tidak terverifikasi tercabut — cek router manual."}
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
