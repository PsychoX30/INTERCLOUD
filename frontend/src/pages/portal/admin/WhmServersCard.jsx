import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Server, Plus, Trash2, Pencil, Zap, Loader2, Scale, X, Package } from "lucide-react";
import { toast } from "sonner";

const EMPTY = {
  name: "",
  host: "",
  username: "",
  api_token: "",
  password: "",
  max_accounts: "",
  ssl_verify: true,
  enabled: true,
};

export const WhmServersCard = () => {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState("");
  const [testRes, setTestRes] = useState({});
  const [capacity, setCapacity] = useState(null);
  const [packages, setPackages] = useState({});

  const load = () => api.get("/admin/cpanel/servers").then((r) => setRows(r.data)).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  const save = async () => {
    setBusy("save");
    try {
      const payload = {
        ...form,
        max_accounts: form.max_accounts ? parseInt(form.max_accounts, 10) : 0,
        sort_order: form.sort_order ? parseInt(form.sort_order, 10) : 100,
      };
      if (form.id) await api.put(`/admin/cpanel/servers/${form.id}`, payload);
      else await api.post("/admin/cpanel/servers", payload);
      toast.success("Server WHM/cPanel disimpan");
      setForm(null);
      load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan server"); }
    finally { setBusy(""); }
  };

  const del = async (r) => {
    if (!window.confirm(`Hapus server WHM '${r.name || r.host}' dari registry? Akun hosting yang sudah aktif tidak terhapus.`)) return;
    try { await api.delete(`/admin/cpanel/servers/${r.id}`); toast.success("Server dihapus"); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const test = async (r) => {
    setBusy(`test-${r.id}`);
    try {
      const { data } = await api.post(`/admin/cpanel/servers/${r.id}/test`);
      setTestRes((p) => ({ ...p, [r.id]: data }));
    } catch (e) {
      setTestRes((p) => ({ ...p, [r.id]: { ok: false, message: e?.response?.data?.detail || "Test gagal" } }));
    } finally { setBusy(""); }
  };

  const listPackages = async (r) => {
    setBusy(`pkg-${r.id}`);
    try {
      const { data } = await api.get(`/admin/cpanel/servers/${r.id}/packages`);
      setPackages((p) => ({ ...p, [r.id]: data.packages || [] }));
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal membaca paket"); }
    finally { setBusy(""); }
  };

  const checkCapacity = async () => {
    setBusy("capacity");
    try { const { data } = await api.get("/admin/cpanel/servers/capacity"); setCapacity(data); }
    catch (e) { toast.error(e?.response?.data?.detail || "Gagal membaca kapasitas"); }
    finally { setBusy(""); }
  };

  return (
    <Card className="p-5 mt-3 border-[#0a2350]/20" data-testid="whm-servers-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-[#0a2350] flex items-center justify-center"><Server className="h-5 w-5 text-[#f5b120]" /></div>
          <div>
            <div className="font-extrabold text-[#0a2350]">Multi-Server WHM/cPanel (Load Balance)</div>
            <p className="text-xs text-slate-500">Daftarkan beberapa node WHM. Saat order hosting, akun cPanel ditempatkan di node dengan <b>slot bebas terbanyak</b> dan memiliki package target. Bila kosong, integrasi cPanel tunggal di atas yang dipakai.</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button className={btnSecondary} onClick={checkCapacity} disabled={busy === "capacity"} data-testid="whm-servers-capacity-btn">
            {busy === "capacity" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scale className="h-4 w-4" />} Cek kapasitas
          </button>
          <button className={btnPrimary} onClick={() => setForm({ ...EMPTY })} data-testid="whm-servers-add-btn">
            <Plus className="h-4 w-4" /> Tambah server
          </button>
        </div>
      </div>

      {capacity && (
        <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-4" data-testid="whm-capacity-report">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Laporan kapasitas live</div>
            <button className="text-slate-400 hover:text-slate-600" onClick={() => setCapacity(null)}><X className="h-4 w-4" /></button>
          </div>
          {capacity.best && (
            <p className="mt-1 text-xs font-semibold text-emerald-700" data-testid="whm-capacity-best">
              Hosting baru akan ditempatkan di: <b>{capacity.best.server}</b>
            </p>
          )}
          <div className="mt-2 space-y-2">
            {(capacity.report || []).map((r, i) => (
              <div key={i} className="text-xs">
                <span className="font-bold text-[#0a2350]">{r.server || "Default"}</span>
                {!r.ok && <span className="ml-2 text-red-600">{r.error || "tidak terjangkau"}</span>}
                {r.ok && (
                  <span className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-white border border-slate-200">
                    {r.accounts}/{r.max_accounts || "∞"} akun · {r.slots} slot bebas · load {r.loadavg?.five?.toFixed?.(2) || "-"} · {r.has_package ? "package tersedia" : "package TIDAK tersedia"}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {rows === null && <div className="text-xs text-slate-400">Memuat…</div>}
        {rows && rows.length === 0 && (
          <p className="text-xs text-slate-400 italic" data-testid="whm-servers-empty">Belum ada server WHM terdaftar - provisioning memakai konfigurasi cPanel tunggal (kartu di atas).</p>
        )}
        {rows && rows.map((r) => (
          <div key={r.id} className="rounded-xl border border-slate-200 bg-white p-3" data-testid={`whm-server-row-${r.id}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-[#0a2350]">{r.name || "Server"}</span>
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${r.enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                    {r.enabled ? "Aktif" : "Nonaktif"}
                  </span>
                </div>
                <div className="text-xs text-slate-500 font-mono truncate">{r.host} · {r.username || "-"} · {r.max_accounts || "∞"} max akun · SSL verify {r.ssl_verify ? "on" : "off"}</div>
              </div>
              <div className="flex gap-1.5">
                <button className={btnSecondary} onClick={() => listPackages(r)} disabled={busy === `pkg-${r.id}`} data-testid={`whm-server-pkg-${r.id}`}>
                  {busy === `pkg-${r.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Package className="h-4 w-4" />} Paket
                </button>
                <button className={btnSecondary} onClick={() => test(r)} disabled={busy === `test-${r.id}`} data-testid={`whm-server-test-${r.id}`}>
                  {busy === `test-${r.id}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Test
                </button>
                <button className={btnSecondary} onClick={() => setForm({ ...r, api_token: "", password: "" })} data-testid={`whm-server-edit-${r.id}`}>
                  <Pencil className="h-4 w-4" />
                </button>
                <button className="px-2.5 rounded-xl border border-red-200 text-red-600 hover:bg-red-50" onClick={() => del(r)} data-testid={`whm-server-delete-${r.id}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
            {testRes[r.id] && (
              <div className={`mt-2 text-xs rounded-lg px-3 py-2 border ${testRes[r.id].ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-800"}`} data-testid={`whm-server-test-result-${r.id}`}>
                {testRes[r.id].message}
                {testRes[r.id].ok && (
                  <span className="ml-2 font-semibold">
                    [{testRes[r.id].accounts || 0} akun · load {testRes[r.id].loadavg?.five?.toFixed?.(2) || "-"} · {testRes[r.id].packages?.length || 0} packages]
                  </span>
                )}
              </div>
            )}
            {packages[r.id] && (
              <div className="mt-2 text-xs rounded-lg px-3 py-2 border bg-slate-50 border-slate-200 text-slate-700">
                Packages: {packages[r.id].join(", ") || "(kosong)"}
              </div>
            )}
          </div>
        ))}
      </div>

      {form && (
        <div className="mt-4 rounded-xl border-2 border-[#f5b120]/50 bg-[#f5b120]/5 p-4" data-testid="whm-server-form">
          <div className="font-bold text-[#0a2350] text-sm mb-3">{form.id ? "Edit server" : "Tambah server WHM"}</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <label><div className={labelClass}>Nama server (label)</div>
              <input className={inputClass} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="WHM Jakarta 1" data-testid="whm-form-name" /></label>
            <label><div className={labelClass}>Host URL <span className="text-red-500">*</span></div>
              <input className={inputClass} value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="https://whm.intercloud-digital.com:2087" data-testid="whm-form-host" /></label>
            <label><div className={labelClass}>Username reseller</div>
              <input className={inputClass} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="intercloud" data-testid="whm-form-username" /></label>
            <label><div className={labelClass}>API Token {form.id && <span className="text-slate-400">(kosongkan bila tidak diganti)</span>}</div>
              <input type="password" className={inputClass} value={form.api_token} onChange={(e) => setForm({ ...form, api_token: e.target.value })} placeholder={form.id && form.has_api_token ? "(tersimpan)" : "token"} data-testid="whm-form-api-token" /></label>
            <label><div className={labelClass}>Password (fallback) {form.id && <span className="text-slate-400">(kosongkan bila tidak diganti)</span>}</div>
              <input type="password" className={inputClass} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder={form.id && form.has_password ? "(tersimpan)" : "password"} data-testid="whm-form-password" /></label>
            <label><div className={labelClass}>Max accounts (0 = unlimited)</div>
              <input type="number" className={inputClass} value={form.max_accounts} onChange={(e) => setForm({ ...form, max_accounts: e.target.value })} placeholder="200" data-testid="whm-form-max-accounts" /></label>
            <label><div className={labelClass}>Sort order</div>
              <input type="number" className={inputClass} value={form.sort_order || ""} onChange={(e) => setForm({ ...form, sort_order: e.target.value })} placeholder="100" data-testid="whm-form-sort-order" /></label>
            <label className="flex items-center gap-2 text-sm pt-5">
              <input type="checkbox" checked={!!form.ssl_verify} onChange={(e) => setForm({ ...form, ssl_verify: e.target.checked })} data-testid="whm-form-ssl-verify" />
              <span className="font-semibold text-slate-700">Verifikasi SSL</span>
            </label>
            <label className="flex items-center gap-2 text-sm pt-5">
              <input type="checkbox" checked={!!form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} data-testid="whm-form-enabled" />
              <span className="font-semibold text-slate-700">Sertakan dalam placement</span>
            </label>
          </div>
          <div className="mt-3 flex gap-2">
            <button className={btnPrimary} onClick={save} disabled={busy === "save" || !form.host} data-testid="whm-form-save">
              {busy === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Simpan
            </button>
            <button className={btnSecondary} onClick={() => setForm(null)} data-testid="whm-form-cancel">Batal</button>
          </div>
        </div>
      )}
    </Card>
  );
};

export default WhmServersCard;
