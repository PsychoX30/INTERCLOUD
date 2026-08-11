import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnSecondary, inputClass, labelClass } from "../ui";
import { Network, Plus, Trash2, Pencil, X, Check, Loader2 } from "lucide-react";

const EMPTY = { name: "", upstream_name: "", bgp_community: "", scope_prefixes: "157.20.32.0/24", enabled: true };

const parsePrefixes = (raw) => {
  if (Array.isArray(raw)) return raw.join(", ");
  return String(raw || "");
};

const parsePrefixesOut = (raw) => String(raw || "")
  .split(/[\s,]+/)
  .map((p) => p.trim())
  .filter(Boolean);

export const BGPBlackholeConfig = () => {
  const [items, setItems] = useState(null);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [isAdmin, setIsAdmin] = useState(true);

  useEffect(() => {
    const role = (localStorage.getItem("auth_role") || "").toLowerCase();
    setIsAdmin(role === "admin");
  }, []);

  const load = () =>
    api.get("/admin/noc/bgp-blackhole-configs")
      .then((r) => setItems(r.data || []))
      .catch(() => setItems([]));

  useEffect(() => { load(); }, []);

  const openNew = () => { setForm(EMPTY); setEditing("new"); };
  const openEdit = (r) => {
    setForm({
      name: r.name || "",
      upstream_name: r.upstream_name || "",
      bgp_community: r.bgp_community || "",
      scope_prefixes: parsePrefixes(r.scope_prefixes),
      enabled: !!r.enabled,
    });
    setEditing(r.id);
  };

  const payload = (f) => ({
    name: f.name.trim(),
    upstream_name: f.upstream_name.trim(),
    bgp_community: f.bgp_community.trim(),
    scope_prefixes: parsePrefixesOut(f.scope_prefixes),
    enabled: !!f.enabled,
  });

  const save = async () => {
    const p = payload(form);
    if (!p.name || !p.upstream_name || !p.bgp_community) {
      setErr("Nama, upstream, dan community wajib diisi");
      return;
    }
    setBusy(true); setErr("");
    try {
      if (editing === "new") await api.post("/admin/noc/bgp-blackhole-configs", p);
      else await api.put(`/admin/noc/bgp-blackhole-configs/${editing}`, p);
      setEditing(null);
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal menyimpan konfigurasi BGP");
    } finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!window.confirm("Hapus konfigurasi BGP RTBH ini?")) return;
    await api.delete(`/admin/noc/bgp-blackhole-configs/${id}`);
    load();
  };

  return (
    <Card className="overflow-hidden mb-6" data-testid="bgp-blackhole-config">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <Network className="h-3.5 w-3.5 text-[#f5b120]" /> BGP RTBH (Upstream)
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            Daftarkan upstream BGP yang mendukung Remote Trigger Black Hole. Community (mis. <code>65000:666</code>) digunakan untuk mengumumkan /32 yang di-blackhole ke seluruh peers upstream. Hanya admin yang dapat membuat/mengubah konfigurasi ini.
          </div>
        </div>
        {isAdmin && (
          <button className={btnSecondary} onClick={openNew} data-testid="bgp-bh-add">
            <Plus className="h-4 w-4" /> Tambah Upstream
          </button>
        )}
      </div>

      {isAdmin && editing && (
        <div className="px-5 py-4 bg-[#f5b120]/5 border-b border-[#f5b120]/30" data-testid="bgp-bh-form">
          {err && <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <label><div className={labelClass}>Nama *</div>
              <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="CBN-Primary" data-testid="bgp-bh-name" /></label>
            <label><div className={labelClass}>Upstream *</div>
              <input className={inputClass} value={form.upstream_name} onChange={(e) => setForm({ ...form, upstream_name: e.target.value })} placeholder="CBN / IIX / APJII" data-testid="bgp-bh-upstream" /></label>
            <label><div className={labelClass}>BGP community *</div>
              <input className={inputClass} value={form.bgp_community} onChange={(e) => setForm({ ...form, bgp_community: e.target.value })} placeholder="65000:666" data-testid="bgp-bh-community" /></label>
            <label><div className={labelClass}>Scope prefixes</div>
              <input className={inputClass} value={form.scope_prefixes} onChange={(e) => setForm({ ...form, scope_prefixes: e.target.value })} placeholder="157.20.32.0/24" data-testid="bgp-bh-scope" /></label>
          </div>
          <label className="flex items-center gap-2 mt-3 text-xs">
            <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} data-testid="bgp-bh-enabled" />
            <span>Aktif (community akan dipasang ke announcement)</span>
          </label>
          <div className="mt-3 flex gap-2">
            <button className={btnSecondary} onClick={save} disabled={busy} data-testid="bgp-bh-save">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Simpan
            </button>
            <button className={btnSecondary} onClick={() => setEditing(null)} data-testid="bgp-bh-cancel"><X className="h-4 w-4" /> Batal</button>
          </div>
        </div>
      )}

      <div className="divide-y divide-slate-100">
        {items === null && <div className="px-5 py-6 text-sm text-slate-500">Memuat konfigurasi BGP...</div>}
        {items !== null && items.length === 0 && (
          <div className="px-5 py-6 text-sm text-slate-500" data-testid="bgp-bh-empty">
            Belum ada upstream RTBH yang terdaftar. Hubungi provider Anda untuk nilai community blackhole (umumnya <code>ASN:666</code>).
          </div>
        )}
        {(items || []).map((r) => (
          <div key={r.id} className="px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2" data-testid={`bgp-bh-row-${r.id}`}>
            <span className={`px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase ${r.enabled ? "bg-emerald-100 text-emerald-700 border-emerald-300" : "bg-slate-100 text-slate-500 border-slate-300"}`}>
              {r.enabled ? "Aktif" : "Nonaktif"}
            </span>
            <div className="min-w-[160px]">
              <div className="text-sm font-bold text-[#0a2350]">{r.name}</div>
              <div className="text-[11px] text-slate-500">{r.upstream_name}</div>
            </div>
            <div className="text-xs text-slate-600">
              Community: <code className="font-mono">{r.bgp_community}</code>
            </div>
            <div className="text-[11px] text-slate-500">
              Scope: {(r.scope_prefixes || []).join(", ") || "—"}
            </div>
            {isAdmin && (
              <div className="ml-auto flex items-center gap-1.5">
                <button className="p-1.5 rounded-lg text-slate-500 hover:text-[#0a2350] hover:bg-slate-100" onClick={() => openEdit(r)} data-testid={`bgp-bh-edit-${r.id}`}><Pencil className="h-4 w-4" /></button>
                <button className="p-1.5 rounded-lg text-slate-500 hover:text-red-600 hover:bg-red-50" onClick={() => del(r.id)} data-testid={`bgp-bh-del-${r.id}`}><Trash2 className="h-4 w-4" /></button>
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
};

export default BGPBlackholeConfig;
