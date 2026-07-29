import React, { useState } from "react";
import { Card, btnSecondary, inputClass, labelClass } from "../ui";
import { SlidersHorizontal, Plus, Trash2, Pencil, X, Check } from "lucide-react";

// CRUD lokal (data tiruan) - persistensi & enforcement live menyusul di fase backend.
const DEFAULT_RULES = [
  { id: "r1", name: "Anti UDP Flood", metric: "pps", threshold: 500000, window_s: 60, action: "alert_blackhole", enabled: true },
  { id: "r2", name: "Bandwidth spike", metric: "bps", threshold: 8000000000, window_s: 120, action: "alert", enabled: true },
  { id: "r3", name: "SYN anomaly", metric: "pps", threshold: 250000, window_s: 30, action: "alert", enabled: false },
];

const ACTION_LABELS = { alert: "Alert saja", alert_blackhole: "Alert + auto-blackhole" };
const fmtThreshold = (r) => r.metric === "bps"
  ? `${(r.threshold / 1e9).toLocaleString("id-ID")} Gbps`
  : `${(r.threshold / 1e3).toLocaleString("id-ID")}K pps`;

const EMPTY = { name: "", metric: "pps", threshold: 100000, window_s: 60, action: "alert", enabled: true };

export const ThresholdRules = () => {
  const [rules, setRules] = useState(DEFAULT_RULES);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const openNew = () => { setForm(EMPTY); setEditing("new"); };
  const openEdit = (r) => { setForm({ ...r }); setEditing(r.id); };
  const save = () => {
    if (!form.name.trim()) return;
    if (editing === "new") {
      setRules((rs) => [...rs, { ...form, id: `r${Date.now()}` }]);
    } else {
      setRules((rs) => rs.map((r) => (r.id === editing ? { ...form, id: r.id } : r)));
    }
    setEditing(null);
  };
  const del = (id) => setRules((rs) => rs.filter((r) => r.id !== id));
  const toggle = (id) => setRules((rs) => rs.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)));

  return (
    <Card className="overflow-hidden mb-6" data-testid="threshold-rules">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <SlidersHorizontal className="h-3.5 w-3.5 text-[#f5b120]" /> Ambang Batas Trafik (Mitigasi Otomatis)
          </div>
          <div className="text-xs text-slate-500 mt-0.5">Aturan deteksi anomali (CRUD lokal, data tiruan). Enforcement live menyusul di fase backend.</div>
        </div>
        <button className={btnSecondary} onClick={openNew} data-testid="threshold-add">
          <Plus className="h-4 w-4" /> Tambah Rule
        </button>
      </div>

      {editing && (
        <div className="px-5 py-4 bg-[#f5b120]/5 border-b border-[#f5b120]/30" data-testid="threshold-form">
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
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
              <input type="number" min="10" className={`${inputClass} text-right`} value={form.window_s} onChange={(e) => setForm({ ...form, window_s: Number(e.target.value) })} /></label>
            <label><div className={labelClass}>Aksi</div>
              <select className={inputClass} value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })} data-testid="threshold-action">
                <option value="alert">Alert saja</option>
                <option value="alert_blackhole">Alert + auto-blackhole</option>
              </select></label>
          </div>
          <div className="mt-3 flex gap-2">
            <button className={btnSecondary} onClick={save} data-testid="threshold-save"><Check className="h-4 w-4" /> Simpan</button>
            <button className={btnSecondary} onClick={() => setEditing(null)} data-testid="threshold-cancel"><X className="h-4 w-4" /> Batal</button>
          </div>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {rules.length === 0 && (
          <div className="px-5 py-6 text-sm text-slate-500" data-testid="threshold-empty">Belum ada rule. Klik "Tambah Rule" untuk membuat.</div>
        )}
        {rules.map((r) => (
          <div key={r.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2" data-testid={`threshold-row-${r.id}`}>
            <button
              onClick={() => toggle(r.id)}
              className={`relative h-5 w-9 rounded-full transition-colors ${r.enabled ? "bg-emerald-500" : "bg-slate-300"}`}
              title={r.enabled ? "Aktif" : "Nonaktif"}
              data-testid={`threshold-toggle-${r.id}`}
            >
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${r.enabled ? "left-4.5 translate-x-0 left-[18px]" : "left-0.5"}`} />
            </button>
            <div className="min-w-[160px]">
              <div className={`text-sm font-bold ${r.enabled ? "text-[#0a2350]" : "text-slate-400"}`}>{r.name}</div>
              <div className="text-[11px] text-slate-500">{ACTION_LABELS[r.action]}</div>
            </div>
            <div className="text-xs text-slate-600 tabular-nums">
              &gt; <b>{fmtThreshold(r)}</b> selama {r.window_s}s
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
