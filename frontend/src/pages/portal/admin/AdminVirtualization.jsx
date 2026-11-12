import React, { useState, useEffect } from "react";
import { PageHeader, Card, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Loader2, Server } from "lucide-react";
import { api } from "../../../portal/api";

/* -------------------- Virtualization (Proxmox VE) --------------------
 *
 * Halaman ini dulu adalah tab "Proxmox VE" di dalam menu Provisioning.
 * Dipindah ke menu sendiri karena dua alasan:
 *
 * 1. Provisioning adalah alat PEMULIHAN untuk pesanan yang sudah ada
 *    (auto-provision cPanel gagal -> admin buat akun manual). Proxmox di
 *    sini bukan pemulihan; dia membuat resource baru dari nol.
 * 2. Kalau dibiarkan di Provisioning, admin bisa membuat VM tanpa order dan
 *    tanpa baris `services` -- persis jenis data yatim yang pernah harus
 *    dibersihkan manual dari database produksi.
 *
 * Alur normal pembuatan VM untuk pelanggan tetap lewat order -> payment ->
 * auto-provision. Halaman ini untuk operasi langsung oleh admin/infra.
 */

export const AdminVirtualization = () => {
  return (
    <div>
      <PageHeader
        title="Virtualization"
        subtitle="Buat VM langsung di cluster Proxmox VE. Untuk pelanggan, gunakan alur order agar baris services ikut tercatat."
      />
      <ProxmoxProvision />
    </div>
  );
};

const ProxmoxProvision = () => {
  const [os, setOs] = useState([]);
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [f, setF] = useState({ hostname: "", cores: 2, memory: 2048, disk: 40, node: "" });
  const [reqOpen, setReqOpen] = useState(false);
  const [tplInfo, setTplInfo] = useState(null);

  useEffect(() => {
    api.get("/admin/proxmox/os-options")
      .then((r) => setOs(r.data.options || []))
      .catch(() => setOs([]));
  }, []);
  useEffect(() => {
    api.get("/admin/proxmox/templates")
      .then((r) => setTplInfo(r.data))
      .catch((e) => setTplInfo({ error: e?.response?.data?.detail || "Integrasi Proxmox belum aktif" }));
  }, []);

  const run = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setMsg(null); setErr(null);
    try {
      const { data } = await api.post("/admin/provisioning/proxmox/create", {
        hostname: f.hostname, node: f.node, os: chosen,
        cores: f.cores, memory: f.memory, disk: f.disk,
      });
      if (data.building) setMsg(`⏳ ${data.message}`);
      else setMsg(`✓ ${data.message || `VM "${data.name}" (VMID ${data.vmid}) berhasil dibuat di node ${data.node}.`}`);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Provisioning gagal - periksa integrasi Proxmox.");
    } finally { setBusy(false); }
  };

  const groupedOs = os.reduce((acc, t) => { (acc[t.family] = acc[t.family] || []).push(t); return acc; }, {});

  return (
    <Card className="p-6">
      {tplInfo && (tplInfo.error ? (
        <div className="mb-4 text-xs rounded-xl bg-amber-50 border border-amber-200 text-amber-800 px-3 py-2" data-testid="prov-proxmox-tpl-warn">{tplInfo.error}</div>
      ) : (tplInfo.templates || []).length > 0 ? (
        <div className="mb-4 text-xs rounded-xl bg-blue-50 border border-blue-200 text-blue-800 px-3 py-2" data-testid="prov-proxmox-tpl-info">
          {(() => {
            const t = tplInfo.templates.find((x) => x.vmid === tplInfo.configured_vmid) || tplInfo.templates[0];
            return <>Template clone aktif: <b>{t.name || "VM"}</b> (VMID {t.vmid}) di node {t.node}{!tplInfo.configured_vmid && " - dipilih otomatis. Set 'Clone template VMID' di Integrations untuk mengunci pilihan."}</>;
          })()}
        </div>
      ) : (
        <div className="mb-4 text-xs rounded-xl bg-amber-50 border border-amber-200 text-amber-800 px-3 py-2" data-testid="prov-proxmox-tpl-warn">
          Tidak ada template VM (template=1) di cluster. Buat template terlebih dahulu agar order VPS berbayar bisa auto-provision.
        </div>
      ))}
      <form onSubmit={run} className="grid grid-cols-2 gap-3">
        <label><div className={labelClass}>VM Hostname *</div><input required value={f.hostname} onChange={(e) => setF({ ...f, hostname: e.target.value })} className={inputClass} placeholder="app-prod-01" data-testid="prov-hostname" /></label>
        <label><div className={labelClass}>Target Node</div><input value={f.node} onChange={(e) => setF({ ...f, node: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>vCPU</div><input type="number" min="1" value={f.cores} onChange={(e) => setF({ ...f, cores: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>RAM (MB)</div><input type="number" min="512" value={f.memory} onChange={(e) => setF({ ...f, memory: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Disk (GB)</div><input type="number" min="10" value={f.disk} onChange={(e) => setF({ ...f, disk: e.target.value })} className={inputClass} /></label>

        <div className="col-span-2">
          <div className="flex items-center justify-between mb-2">
            <div className={labelClass}>OS - LIVE dari Proxmox (template, ISO & katalog cloud image)</div>
            <button type="button" className="text-xs font-bold text-[#f5b120] hover:text-[#0a2350]" onClick={() => setReqOpen(true)}>OS not listed? Request one →</button>
          </div>
          <div className="rounded-xl border border-slate-200 max-h-56 overflow-y-auto divide-y divide-slate-100">
            {Object.keys(groupedOs).length === 0 && <div className="p-4 text-sm text-slate-500">Loading OS dari server Proxmox…</div>}
            {Object.entries(groupedOs).map(([fam, list]) => (
              <div key={fam}>
                <div className="px-3 py-1.5 text-[10px] uppercase tracking-widest font-bold text-slate-500 bg-slate-50">{fam}</div>
                {list.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setChosen(t.key)}
                    className={`w-full text-left px-3 py-2 text-sm ${chosen === t.key ? "bg-[#f5b120]/15 text-[#0a2350] font-bold" : "hover:bg-slate-50"}`}
                    data-testid={`os-${t.key}`}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate">{t.label}</span>
                      <span className="text-[10px] uppercase tracking-widest text-slate-400 shrink-0">{t.type}</span>
                    </span>
                    {t.note && <span className="block text-[10px] text-slate-400">{t.note}</span>}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>

        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button className={btnPrimary} disabled={busy || !chosen} data-testid="prov-submit">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Provision VM
          </button>
        </div>
      </form>
      {msg && <div className="mt-4 text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-2" data-testid="prov-proxmox-ok">{msg}</div>}
      {err && <div className="mt-4 text-sm rounded-xl bg-red-50 border border-red-200 text-red-700 px-3 py-2" data-testid="prov-proxmox-err">{err}</div>}

      {reqOpen && <OsRequestDialog onClose={() => setReqOpen(false)} />}
    </Card>
  );
};

const OsRequestDialog = ({ onClose }) => {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true);
    try {
      const { data } = await api.post("/client/proxmox/os-request", { os_name: name, notes });
      setDone(data);
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-md bg-white rounded-3xl p-6" data-testid="os-request-form">
        <h3 className="text-xl font-extrabold text-[#0a2350]">Request OS Template</h3>
        <p className="text-sm text-slate-500 mt-1">This opens a technical ticket asking our engineers to add the OS ISO to Proxmox storage.</p>
        {done ? (
          <div className="mt-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-2 text-sm">
            ✓ Ticket <b>{done.ticket_number}</b> created. Our team will get back to you shortly.
            <div className="mt-3 flex justify-end"><button type="button" className={btnPrimary} onClick={onClose}>Close</button></div>
          </div>
        ) : (
          <>
            <label className="block mt-4"><div className={labelClass}>OS name *</div><input required value={name} onChange={(e) => setName(e.target.value)} className={inputClass} placeholder="AlmaLinux 9, FreeBSD 14…" data-testid="os-req-name" /></label>
            <label className="block mt-3"><div className={labelClass}>Notes</div><textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} className={`${inputClass} h-auto py-2`} /></label>
            <div className="mt-5 flex justify-end gap-2">
              <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
              <button type="submit" disabled={busy || !name} className={btnPrimary} data-testid="os-req-submit">{busy ? "Sending…" : "Send request"}</button>
            </div>
          </>
        )}
      </form>
    </div>
  );
};
