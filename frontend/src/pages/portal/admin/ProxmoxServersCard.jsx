import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Server, Plus, Trash2, Pencil, Zap, Loader2, Scale, X } from "lucide-react";
import { toast } from "sonner";

const EMPTY = { name: "", host: "", token_id: "", token_secret: "", default_node: "", default_storage: "local-lvm", default_bridge: "vmbr0", enabled: true };

export const ProxmoxServersCard = () => {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState("");
  const [testRes, setTestRes] = useState({});
  const [capacity, setCapacity] = useState(null);

  const load = () => api.get("/admin/proxmox/servers").then((r) => setRows(r.data)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const save = async () => {
    setBusy("save");
    try {
      if (form.id) await api.put(`/admin/proxmox/servers/${form.id}`, form);
      else await api.post("/admin/proxmox/servers", form);
      toast.success("Server Proxmox disimpan");
      setForm(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan server"); }
    finally { setBusy(""); }
  };

  const del = async (r) => {
    if (!window.confirm(`Hapus server '${r.name || r.host}' dari registry? VM yang sudah berjalan tidak terhapus.`)) return;
    try { await api.delete(`/admin/proxmox/servers/${r.id}`); toast.success("Server dihapus"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const test = async (r) => {
    setBusy(`test-${r.id}`);
    try {
      const { data } = await api.post(`/admin/proxmox/servers/${r.id}/test`);
      setTestRes((p) => ({ ...p, [r.id]: data }));
    } catch (e) {
      setTestRes((p) => ({ ...p, [r.id]: { ok: false, message: e?.response?.data?.detail || "Test gagal" } }));
    } finally { setBusy(""); }
  };

  const checkCapacity = async () => {
    setBusy("capacity");
    try { const { data } = await api.get("/admin/proxmox/servers/capacity"); setCapacity(data); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal membaca kapasitas"); }
    finally { setBusy(""); }
  };

  return (
    <Card className="p-5 mt-3 border-[#0a2350]/20" data-testid="proxmox-servers-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-[#0a2350] flex items-center justify-center"><Server className="h-5 w-5 text-[#f5b120]" /></div>
          <div>
            <div className="font-extrabold text-[#0a2350]">Multi-Server Proxmox (Load Balance)</div>
            <p className="text-xs text-slate-500">Daftarkan beberapa server. Saat provisioning, VM otomatis dibuat di server/node dengan <b>RAM bebas terbanyak</b>. Bila kosong, kartu Proxmox tunggal di atas yang dipakai.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button className={btnSecondary} onClick={checkCapacity} disabled={busy === "capacity"} data-testid="px-servers-capacity-btn">
            {busy === "capacity" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />} Cek kapasitas
          </button>
          <button className={btnPrimary} onClick={() => setForm({ ...EMPTY })} data-testid="px-servers-add-btn">
            <Plus className="h-4 w-4" /> Tambah server
          </button>
        </div>
      </div>

      {capacity && (
        <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4" data-testid="px-capacity-report">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Laporan kapasitas live</div>
            <button className="text-slate-400 hover:text-slate-600" onClick={() => setCapacity(null)}><X className="h-4 w-4" /></button>
          </div>
          {capacity.best && (
            <p className="mt-1 text-xs font-semibold text-emerald-700" data-testid="px-capacity-best">
              VM baru akan ditempatkan di: <b>{capacity.best.server}</b> / node <b>{capacity.best.node}</b> ({Math.round(capacity.best.free_mem_mb / 1024)} GB RAM bebas)
            </p>
          )}
          <div className="mt-2 space-y-2">
            {(capacity.report || []).map((r, i) => (
              <div key={i} className="text-xs">
                <span className="font-bold text-[#0a2350]">{r.server || "Default"}</span>
                {!r.ok && <span className="ml-2 text-red-600">{r.error || "tidak terjangkau"}</span>}
                {r.ok && (r.nodes || []).map((n) => (
                  <span key={n.node} className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-white border border-slate-200">
                    {n.node}: {Math.round(n.free_mem_mb / 1024)}/{Math.round(n.total_mem_mb / 1024)} GB bebas · CPU {n.cpu_used_pct}%
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {rows === null && <div className="text-xs text-slate-400">Memuat…</div>}
        {rows && rows.length === 0 && (
          <p className="text-xs text-slate-400 italic" data-testid="px-servers-empty">Belum ada server terdaftar - provisioning memakai konfigurasi Proxmox tunggal (kartu di atas).</p>
        )}
        {rows && rows.map((r) => (
          <div key={r.id} className="rounded-xl border border-slate-200 bg-white p-3" data-testid={`px-server-row-${r.id}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-[#0a2350]">{r.name || "Server"}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${r.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                    {r.enabled ? "Aktif" : "Nonaktif"}
                  </span>
                </div>
                <div className="text-xs text-slate-500 font-mono truncate">{r.host} · {r.token_id || r.username || "-"}</div>
              </div>
              <div className="flex gap-1.5">
                <button className={btnSecondary} onClick={() => test(r)} disabled={busy === `test-${r.id}`} data-testid={`px-server-test-${r.id}`}>
                  {busy === `test-${r.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Test
                </button>
                <button className={btnSecondary} onClick={() => setForm({ ...r, token_secret: "" })} data-testid={`px-server-edit-${r.id}`}>
                  <Pencil className="h-4 w-4" />
                </button>
                <button className="px-2.5 rounded-xl border border-red-200 text-red-600 hover:bg-red-50" onClick={() => del(r)} data-testid={`px-server-delete-${r.id}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
            {testRes[r.id] && (
              <div className={`mt-2 text-xs rounded-lg px-3 py-2 border ${testRes[r.id].ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-800"}`} data-testid={`px-server-test-result-${r.id}`}>
                {testRes[r.id].message}
                {testRes[r.id].ok && (testRes[r.id].nodes || []).map((n) => (
                  <span key={n.node} className="ml-2 font-semibold">[{n.node}: {Math.round(n.free_mem_mb / 1024)} GB RAM bebas]</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {form && (
        <div className="mt-4 rounded-xl border-2 border-[#f5b120]/50 bg-[#f5b120]/5 p-4" data-testid="px-server-form">
          <div className="font-bold text-[#0a2350] text-sm mb-3">{form.id ? "Edit server" : "Tambah server Proxmox"}</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label><div className={labelClass}>Nama server (label)</div>
              <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="PVE Jakarta 1" data-testid="px-form-name" /></label>
            <label><div className={labelClass}>Host URL <span className="text-red-500">*</span></div>
              <input className={inputClass} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="https://10.0.0.1:8006" data-testid="px-form-host" /></label>
            <label><div className={labelClass}>API Token ID</div>
              <input className={inputClass} value={form.token_id} onChange={(e) => setForm({ ...form, token_id: e.target.value })} placeholder="root@pam!portal" data-testid="px-form-token-id" /></label>
            <label><div className={labelClass}>API Token Secret {form.id && <span className="text-slate-400">(kosongkan bila tidak diganti)</span>}</div>
              <input type="password" className={inputClass} value={form.token_secret} onChange={(e) => setForm({ ...form, token_secret: e.target.value })} placeholder={form.id && form.has_secret ? "(tersimpan)" : "secret"} data-testid="px-form-token-secret" /></label>
            <label><div className={labelClass}>Default node</div>
              <input className={inputClass} value={form.default_node} onChange={(e) => setForm({ ...form, default_node: e.target.value })} placeholder="node1" data-testid="px-form-node" /></label>
            <label><div className={labelClass}>Default storage</div>
              <input className={inputClass} value={form.default_storage} onChange={(e) => setForm({ ...form, default_storage: e.target.value })} placeholder="local-lvm" data-testid="px-form-storage" /></label>
            <label><div className={labelClass}>Default bridge</div>
              <input className={inputClass} value={form.default_bridge} onChange={(e) => setForm({ ...form, default_bridge: e.target.value })} placeholder="vmbr0" data-testid="px-form-bridge" /></label>
            <label className="flex items-center gap-2 text-sm pt-5">
              <input type="checkbox" checked={!!form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} data-testid="px-form-enabled" />
              <span className="font-semibold text-slate-700">Sertakan dalam load balance</span>
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <button className={btnPrimary} onClick={save} disabled={busy === "save" || !form.host} data-testid="px-form-save">
              {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Simpan
            </button>
            <button className={btnSecondary} onClick={() => setForm(null)} data-testid="px-form-cancel">Batal</button>
          </div>
        </div>
      )}
    </Card>
  );
};

export default ProxmoxServersCard;
