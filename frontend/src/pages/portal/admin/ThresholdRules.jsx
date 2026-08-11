import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnSecondary, inputClass, labelClass } from "../ui";
import { SlidersHorizontal, Plus, Trash2, Pencil, X, Check, Loader2 } from "lucide-react";

const ACTION_LABELS = {
  alert: "Alert saja",
  alert_blackhole: "Alert + auto-blackhole",
  alert_bgp_blackhole: "Alert + BGP RTBH (auto)",
};
const DIRECTION_LABELS = { inbound: "Inbound (luar → dalam)", outbound: "Outbound (dalam → luar)", any: "Semua arah" };
const fmtThreshold = (r) => r.metric === "bps"
  ? `${(r.threshold / 1e9).toLocaleString("id-ID")} Gbps`
  : `${(r.threshold / 1e3).toLocaleString("id-ID")}K pps`;

const EMPTY = { name: "", metric: "pps", threshold: 100000, window_s: 60, action: "alert", direction: "inbound", scope_prefixes: "157.20.32.0/24", enabled: true };

export const ThresholdRules = () => {
  const [rules, setRules] = useState(null);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = () => api.get("/admin/noc/threshold-rules").then((r) => setRules(r.data)).catch(() => setRules([]));
  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(EMPTY); setEditing("new"); };
  const openEdit = (r) => { setForm({ ...r, scope_prefixes: (r.scope_prefixes || []).join(", ") }); setEditing(r.id); };

  const payload = (f) => ({
    name: f.name, metric: f.metric, threshold: Number(f.threshold),
    window_s: Number(f.window_s), action: f.action, enabled: !!f.enabled,
    direction: f.direction || "inbound",
    scope_prefixes: String(f.scope_prefixes || "")
      .split(/[\s,]+/)
      .map((p) => p.trim())
      .filter(Boolean),
  });

  const save = async () => {
    if (!form.name.trim()) return;
    setBusy(true); setErr("");
    try {
      if (editing === "new") await api.post("/admin/noc/threshold-rules", payload(form));
      else await api.put(`/admin/noc/threshold-rules/${editing}`, payload(form));
      setEditing(null);
      load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal menyimpan rule");
    } finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Hapus rule ini?")) return;
    await api.delete(`/admin/noc/threshold-rules/${id}`);
    load();
  };
  const toggle = async (r) => {
    await api.put(`/admin/noc/threshold-rules/${r.id}`, payload({ ...r, enabled: !r.enabled }));
    load();
  };

  return (
    <Card className="overflow-hidden mb-6" data-testid="threshold-rules">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <SlidersHorizontal className="h-3.5 w-3.5 text-[#f5b120]" /> Ambang Batas Trafik (Mitigasi Otomatis)
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Rule tersimpan di server dan dievaluasi otomatis tiap 5 menit terhadap sampel trafik live.</div>
        </div>
        <button className={btnSecondary} onClick={openNew} data-testid="threshold-add">
          <Plus className="h-4 w-4" /> Tambah Rule
        </button>
      </div>

      {editing && (
        <div className="px-5 py-4 bg-[#f5b120]/5 border-b border-[#f5b120]/30" data-testid="threshold-form">
          {err && <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <label><div className={labelClass}>Nama rule *</div>
              <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="threshold-name" /></label>
            <label><div className={labelClass}>Metrik</div>
              <select className={inputClass} value={form.metric} onChange={(e) => setForm({ ...form, metric: e.target.value })} data-testid="threshold-metric">
                <option value="pps">Packets/s (pps)</option>
                <option value="bps">Bandwidth (bps)</option>
              </select></label>
            <label><div className={labelClass}>Ambang batas</div>
              <input type="number" min="1" className={`${inputClass} text-right`} value={form.threshold} onChange={(e) => setForm({ ...form, threshold: Number(e.target.value) })} data-testid="threshold-value" /></label>
            <label><div className={labelClass}>Window (detik)</div>
              <input type="number" min="60" className={`${inputClass} text-right`} value={form.window_s} onChange={(e) => setForm({ ...form, window_s: Number(e.target.value) })} /></label>
            <label><div className={labelClass}>Arah serangan</div>
              <select className={inputClass} value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })} data-testid="threshold-direction">
                <option value="inbound">Inbound (luar → dalam)</option>
                <option value="outbound">Outbound (dalam → luar)</option>
                <option value="any">Semua arah</option>
              </select></label>
            <label><div className={labelClass}>Aksi</div>
              <select className={inputClass} value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })} data-testid="threshold-action">
                <option value="alert">Alert saja</option>
                <option value="alert_blackhole">Alert + auto-blackhole</option>
                <option value="alert_bgp_blackhole">Alert + BGP RTBH (auto)</option>
              </select></label>
          </div>
          <label className="block mt-3"><div className={labelClass}>Scope prefixes (dipisah koma)</div>
            <input className={inputClass} value={form.scope_prefixes} onChange={(e) => setForm({ ...form, scope_prefixes: e.target.value })} placeholder="157.20.32.0/24" data-testid="threshold-scope" /></label>
          <div className="mt-3 flex gap-2">
            <button className={btnSecondary} onClick={save} disabled={busy} data-testid="threshold-save">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Simpan
            </button>
            <button className={btnSecondary} onClick={() => setEditing(null)} data-testid="threshold-cancel"><X className="h-4 w-4" /> Batal</button>
          </div>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {rules === null && (
          <div className="px-5 py-6 text-sm text-slate-500">Memuat rule...</div>
        )}
        {rules !== null && rules.length === 0 && (
          <div className="px-5 py-6 text-sm text-slate-500" data-testid="threshold-empty">Belum ada rule. Klik "Tambah Rule" untuk membuat.</div>
        )}
        {(rules || []).map((r) => (
          <div key={r.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2" data-testid={`threshold-row-${r.id}`}>
            <button
              onClick={() => toggle(r)}
              className={`relative h-5 w-9 rounded-full transition-colors ${r.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
              title={r.enabled ? "Aktif" : "Nonaktif"}
              data-testid={`threshold-toggle-${r.id}`}
            >
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${r.enabled ? "left-[18px]" : "left-0.5"}`} />
            </button>
            <div className="min-w-[160px]">
              <div className={`text-sm font-bold ${r.enabled ? "text-[#0a2350]" : "text-slate-400"}`}>{r.name}</div>
              <div className="text-[11px] text-slate-500">{ACTION_LABELS[r.action]} · {DIRECTION_LABELS[r.direction] || r.direction}</div>
            </div>
            <div className="text-xs text-slate-600 tabular-nums">
              &gt; <b>{fmtThreshold(r)}</b> selama {r.window_s}s
            </div>
            <div className="text-[11px] text-slate-500">
              Scope: {(r.scope_prefixes || []).join(", ") || "157.20.32.0/24"}
            </div>
            <div className="ml-auto flex items-center gap-1.5">
              <button className="p-1.5 rounded-lg text-slate-500 hover:text-[#0a2350] hover:bg-slate-100" onClick={() => openEdit(r)} data-testid={`threshold-edit-${r.id}`}><Pencil className="h-4 w-4" /></button>
              <button className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50" onClick={() => del(r.id)} data-testid={`threshold-del-${r.id}`}><Trash2 className="h-4 w-4" /></button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
};

export default ThresholdRules;
