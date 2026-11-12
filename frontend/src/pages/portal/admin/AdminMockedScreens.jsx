import React, { useState, useEffect } from "react";
import { PageHeader, Card, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Loader2 } from "lucide-react";
import { api } from "../../../portal/api";

/* -------------------- Provisioning manual (cPanel/WHM) --------------------
 *
 * Halaman ini SENGAJA hanya punya satu jalur: provisioning manual cPanel/WHM.
 *
 * Tab yang dulu ada di sini dan alasannya dihapus:
 * - "Order → Payment → Deploy": diagram statis tanpa backend sama sekali.
 * - "Plesk": provider tidak pernah terdaftar di integration_settings, sehingga
 *   tombol Provision selalu gagal dengan "Integrasi Plesk belum aktif".
 * - "Proxmox VE": fungsinya nyata, tapi memindahkannya ke sini membuat admin
 *   dapat membuat VM tanpa order dan tanpa baris `services` -- sumber data
 *   yatim. Sudah dipindah ke menu Virtualization (AdminVirtualization).
 *
 * Yang tersisa adalah alat pemulihan: ketika auto-provision dari order gagal,
 * admin membuat akun hosting-nya manual di sini. Panel ditentukan oleh
 * integrasi yang aktif (cPanel), bukan oleh pilihan tab.
 */
export const AdminProvisioning = () => {
  return (
    <div>
      <PageHeader
        title="Provisioning"
        subtitle="Pembuatan akun hosting manual di cPanel/WHM. Dipakai saat auto-provision dari order gagal."
      />
      <ProvisionForm
        module="cPanel"
        fields={[
          ["username", "Cust Username"],
          ["domain", "Primary Domain"],
          ["plan", "Package Plan"],
          ["password", "Initial Password", "password"],
        ]}
      />
    </div>
  );
};

const ProvisionForm = ({ module, fields }) => {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [f, setF] = useState({});
  const panelKey = module === "cPanel" ? "cpanel" : module.toLowerCase();
  const run = async (e) => {
    e.preventDefault(); setBusy(true); setMsg(null); setErr(null);
    try {
      const { data } = await api.post("/admin/provisioning/hosting/create", {
        panel: panelKey, domain: f.domain, username: f.username,
        password: f.password, plan: f.plan,
      });
      setMsg(`✓ Akun ${data.panel} "${data.username}" berhasil dibuat untuk ${data.domain}.`);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || `Provisioning ${module} gagal - periksa integrasi.`);
    } finally { setBusy(false); }
  };
  return (
    <Card className="p-6">
      <form onSubmit={run} className="grid grid-cols-2 gap-3">
        {fields.map(([k, l, t]) => (
          <label key={k}>
            <div className={labelClass}>{l}</div>
            <input required type={t || "text"} value={f[k] || ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} className={inputClass} data-testid={`prov-${k}`} />
          </label>
        ))}
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button className={btnPrimary} disabled={busy} data-testid="prov-submit">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Provision</button>
        </div>
      </form>
      {msg && <div className="mt-4 text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-2" data-testid="prov-hosting-ok">{msg}</div>}
      {err && <div className="mt-4 text-sm rounded-xl bg-red-50 border border-red-200 text-red-700 px-3 py-2" data-testid="prov-hosting-err">{err}</div>}
    </Card>
  );
};

/* -------------------- DCIM & IPAM (native, live, editable) -------------------- */
export const AdminDCIM = () => {
  const [tab, setTab] = useState("racks");
  return (
    <div>
      <PageHeader title="DCIM & IPAM" subtitle="Live, editable rack and IP address management - inspired by NetBox but native to this console." />
      <div className="flex gap-2 border-b border-slate-200 mb-4">
        {[["racks", "Racks"], ["prefixes", "Prefixes"], ["ips", "IP Addresses"], ["sites", "Sites"]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} data-testid={`dcim-tab-${k}`}
            className={`px-4 h-11 -mb-px border-b-2 text-sm font-bold ${tab === k ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500"}`}>{l}</button>
        ))}
      </div>
      {tab === "racks" && <RacksTab />}
      {tab === "prefixes" && <PrefixesTab />}
      {tab === "ips" && <IPsTab />}
      {tab === "sites" && <SitesTab />}
    </div>
  );
};

const DModal = ({ title, onClose, children }) => (
  <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()} className="w-full max-w-xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto">
      <h3 className="text-xl font-extrabold text-[#0a2350] mb-4">{title}</h3>
      {children}
    </div>
  </div>
);

/* ---- Racks ---- */
const RacksTab = () => {
  const [racks, setRacks] = useState(null);
  const [editing, setEditing] = useState(null);
  const [rackForm, setRackForm] = useState(null); // {new/obj}
  const load = () => api.get("/admin/dcim/racks").then((r) => setRacks(r.data));
  useEffect(() => { load(); }, []);
  if (!racks) return <div className="text-sm text-slate-500 py-10 text-center">Loading…</div>;
  const del = async (id) => { if (window.confirm("Delete rack?")) { await api.delete(`/admin/dcim/racks/${id}`); load(); } };
  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button className={btnPrimary} onClick={() => setRackForm("new")}><span className="text-lg">+</span> New Rack</button>
      </div>
      <div className="grid lg:grid-cols-3 gap-4">
        {racks.map((r) => {
          const pct = (r.power_draw_w / r.power_cap_w) * 100;
          return (
            <Card key={r.id} className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm font-extrabold text-[#0a2350]">{r.name}</div>
                  <div className="text-xs text-slate-500">{r.site}</div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setEditing(r)} className="text-slate-500 hover:text-[#f5b120] text-xs font-bold">Edit U</button>
                  <button onClick={() => setRackForm(r)} className="text-slate-500 hover:text-[#f5b120] text-xs font-bold">Config</button>
                  <button onClick={() => del(r.id)} className="text-slate-500 hover:text-red-600 text-xs font-bold">×</button>
                </div>
              </div>
              <div className="mt-2 h-2 bg-slate-100 rounded overflow-hidden">
                <div className={`h-full ${pct > 80 ? "bg-red-500" : "bg-emerald-500"}`} style={{ width: `${Math.min(100, pct)}%` }} />
              </div>
              <div className="mt-1 text-[11px] text-slate-500">{r.power_draw_w}/{r.power_cap_w} W · {pct.toFixed(0)}%</div>
              {/* Rack elevation - one segment per U, coloured by occupancy */}
              <div className="mt-3">
                <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-slate-400 mb-1">
                  <span>Elevation (U{r.u_size} → U1)</span>
                  <span data-testid={`rack-elevation-pct-${r.id}`}>
                    {(() => {
                      const occ = Array.from({ length: r.u_size }, (_, i) => i + 1)
                        .filter((u) => r.occupancy?.some((o) => u >= o.u_bot && u <= o.u_top)).length;
                      return `${occ}/${r.u_size} U used`;
                    })()}
                  </span>
                </div>
                <div className="flex gap-px rounded overflow-hidden border border-slate-200" data-testid={`rack-elevation-${r.id}`}>
                  {Array.from({ length: r.u_size }, (_, i) => r.u_size - i).map((u) => {
                    const hit = r.occupancy?.find((o) => u >= o.u_bot && u <= o.u_top);
                    const cls = hit
                      ? (hit.customer && hit.customer !== "internal" ? "bg-[#f5b120]" : "bg-slate-500")
                      : "bg-slate-100";
                    return <span key={u} className={`h-4 flex-1 ${cls}`} title={`U${u}: ${hit ? hit.label : "free"}`} />;
                  })}
                </div>
                <div className="mt-1 flex items-center gap-3 text-[9px] text-slate-400">
                  <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-[#f5b120]" /> customer</span>
                  <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-slate-500" /> internal</span>
                  <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-slate-100 border border-slate-200" /> free</span>
                </div>
              </div>
              <div className="mt-3 rounded-xl border border-slate-200 divide-y divide-slate-100 max-h-60 overflow-y-auto">
                {Array.from({ length: r.u_size }, (_, i) => r.u_size - i).map((u) => {
                  const hit = r.occupancy?.find((o) => u >= o.u_bot && u <= o.u_top);
                  return (
                    <div key={u} className={`flex items-center gap-2 px-3 py-1 text-[11px] font-mono ${hit ? (hit.customer && hit.customer !== "internal" ? "bg-[#f5b120]/10 text-[#0a2350] font-bold" : "bg-slate-50 text-slate-600") : "text-slate-400"}`}>
                      <span className="w-6 text-slate-400">U{u}</span>
                      <span className="flex-1 truncate">{hit ? hit.label : "empty"}</span>
                      {hit?.customer && hit.customer !== "internal" && <span className="text-[9px] uppercase font-bold text-[#f5b120]">{hit.customer}</span>}
                    </div>
                  );
                })}
              </div>
            </Card>
          );
        })}
      </div>
      {editing && <OccupancyEditor rack={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
      {rackForm && <RackForm rack={rackForm === "new" ? null : rackForm} onClose={() => setRackForm(null)} onDone={() => { setRackForm(null); load(); }} />}
    </div>
  );
};

const RackForm = ({ rack, onClose, onDone }) => {
  const [f, setF] = useState({
    name: rack?.name || "", site: rack?.site || "",
    u_size: rack?.u_size || 42,
    power_draw_w: rack?.power_draw_w || 0,
    power_cap_w: rack?.power_cap_w || 6000,
  });
  const submit = async (e) => {
    e.preventDefault();
    if (rack) await api.put(`/admin/dcim/racks/${rack.id}`, f);
    else await api.post("/admin/dcim/racks", { ...f, occupancy: [] });
    onDone();
  };
  return (
    <DModal title={rack ? "Edit rack" : "New rack"} onClose={onClose}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3" data-testid="rack-form">
        <label className="col-span-2"><div className={labelClass}>Rack name *</div><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Site</div><input value={f.site} onChange={(e) => setF({ ...f, site: e.target.value })} className={inputClass} placeholder="Cyber 1 - Metta" /></label>
        <label><div className={labelClass}>U size</div><input type="number" min="1" value={f.u_size} onChange={(e) => setF({ ...f, u_size: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Power cap (W)</div><input type="number" min="0" value={f.power_cap_w} onChange={(e) => setF({ ...f, power_cap_w: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Power draw (W)</div><input type="number" min="0" value={f.power_draw_w} onChange={(e) => setF({ ...f, power_draw_w: e.target.value })} className={inputClass} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </DModal>
  );
};

const OccupancyEditor = ({ rack, onClose, onDone }) => {
  const [rows, setRows] = useState(rack.occupancy || []);
  const [nr, setNr] = useState({ u_top: rack.u_size, u_bot: rack.u_size, label: "", customer: "" });
  const add = () => { if (!nr.label) return; setRows([...rows, { ...nr, u_top: Number(nr.u_top), u_bot: Number(nr.u_bot) }]); setNr({ ...nr, label: "", customer: "" }); };
  const remove = (i) => setRows(rows.filter((_, x) => x !== i));
  const save = async () => { await api.put(`/admin/dcim/racks/${rack.id}`, { occupancy: rows }); onDone(); };
  return (
    <DModal title={`Occupancy - ${rack.name}`} onClose={onClose}>
      <div className="space-y-2 max-h-60 overflow-y-auto mb-3">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-sm">
            <span className="font-mono w-20 text-xs">U{r.u_bot}-U{r.u_top}</span>
            <span className="flex-1 truncate font-semibold text-[#0a2350]">{r.label}</span>
            <span className="text-xs text-slate-500">{r.customer || "-"}</span>
            <button onClick={() => remove(i)} className="text-slate-400 hover:text-red-600">×</button>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-6 gap-2 items-end">
        <label className="col-span-1"><div className={labelClass}>U bot</div><input type="number" min="1" max={rack.u_size} value={nr.u_bot} onChange={(e) => setNr({ ...nr, u_bot: e.target.value })} className={inputClass} /></label>
        <label className="col-span-1"><div className={labelClass}>U top</div><input type="number" min="1" max={rack.u_size} value={nr.u_top} onChange={(e) => setNr({ ...nr, u_top: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Label</div><input value={nr.label} onChange={(e) => setNr({ ...nr, label: e.target.value })} className={inputClass} placeholder="1U Server" /></label>
        <label className="col-span-2"><div className={labelClass}>Customer</div><input value={nr.customer} onChange={(e) => setNr({ ...nr, customer: e.target.value })} className={inputClass} placeholder="internal / PT Foo" /></label>
      </div>
      <div className="mt-3 flex justify-between">
        <button type="button" onClick={add} className={btnSecondary}>+ Add row</button>
        <div className="flex gap-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="button" onClick={save} className={btnPrimary} data-testid="rack-occ-save">Save layout</button>
        </div>
      </div>
    </DModal>
  );
};

/* ---- Prefixes ---- */
const PrefixesTab = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/admin/dcim/prefixes").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <div className="text-sm text-slate-500 py-10 text-center">Loading…</div>;
  const del = async (id) => { if (window.confirm("Delete prefix?")) { await api.delete(`/admin/dcim/prefixes/${id}`); load(); } };
  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button className={btnPrimary} onClick={() => setEditing("new")}>+ New Prefix</button>
      </div>
      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr><th className="px-4 py-3 text-left">Prefix</th><th className="px-4 py-3 text-left">Family</th><th className="px-4 py-3 text-left">Usage</th><th className="px-4 py-3 text-left">VLAN</th><th className="px-4 py-3 text-left">Site</th><th className="px-4 py-3 text-right"></th></tr>
          </thead>
          <tbody>{rows.map((p) => (
            <tr key={p.id} className="border-t border-slate-100">
              <td className="px-4 py-3 font-mono">
                {p.prefix}
                {p.vps_provision && <span className="ml-2 text-[9px] font-bold uppercase tracking-widest bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded" data-testid={`prefix-vps-badge-${p.id}`}>VPS Pool</span>}
              </td>
              <td className="px-4 py-3 text-xs">IPv{p.family}</td>
              <td className="px-4 py-3">
                {(() => {
                  const upct = p.capacity ? Math.min(100, (p.usage / p.capacity) * 100) : 0;
                  return (
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-24 bg-slate-100 rounded overflow-hidden">
                        <div className={`h-full ${upct > 85 ? "bg-red-500" : upct > 60 ? "bg-amber-500" : "bg-[#0a2350]"}`} style={{ width: `${upct}%` }} />
                      </div>
                      <span className="text-xs">{p.usage} / {p.capacity}</span>
                      <span className={`text-[10px] font-bold ${upct > 85 ? "text-red-600" : "text-slate-400"}`} data-testid={`prefix-util-${p.id}`}>{upct.toFixed(0)}%</span>
                    </div>
                  );
                })()}
              </td>
              <td className="px-4 py-3 font-mono text-xs text-slate-500">{p.vlan}</td>
              <td className="px-4 py-3">{p.site}</td>
              <td className="px-4 py-3 text-right whitespace-nowrap">
                {p.family === 4 && (
                  <button className="text-emerald-700 hover:text-emerald-900 font-bold text-xs mr-3" data-testid={`prefix-allocate-${p.id}`}
                    onClick={async () => {
                      const hostname = window.prompt("Hostname untuk IP yang dialokasikan (opsional):", "");
                      if (hostname === null) return;
                      try {
                        const r = await api.post(`/admin/dcim/prefixes/${p.id}/allocate`, { hostname });
                        window.alert(`IP ${r.data.address} berhasil dialokasikan dari ${r.data.prefix}`);
                        load();
                      } catch (e) { window.alert(e?.response?.data?.detail || "Gagal alokasi IP"); }
                    }}>
                    Allocate IP
                  </button>
                )}
                <button className="text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(p)}>Edit</button>
                <button className="ml-3 text-slate-500 hover:text-red-600" onClick={() => del(p.id)}>×</button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      {editing && <PrefixForm p={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    </div>
  );
};

const PrefixForm = ({ p, onClose, onDone }) => {
  const [f, setF] = useState({
    prefix: p?.prefix || "", family: p?.family || 4,
    usage: p?.usage || 0, capacity: p?.capacity || 256,
    vlan: p?.vlan || "", site: p?.site || "",
    gateway: p?.gateway || "", vps_provision: !!p?.vps_provision,
  });
  const submit = async (e) => {
    e.preventDefault();
    const payload = { ...f, family: Number(f.family), usage: Number(f.usage), capacity: Number(f.capacity) };
    if (p) await api.put(`/admin/dcim/prefixes/${p.id}`, payload);
    else await api.post("/admin/dcim/prefixes", payload);
    onDone();
  };
  return (
    <DModal title={p ? "Edit prefix" : "New prefix"} onClose={onClose}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Prefix *</div><input required value={f.prefix} onChange={(e) => setF({ ...f, prefix: e.target.value })} className={`${inputClass} font-mono`} placeholder="103.28.14.0/24" /></label>
        <label><div className={labelClass}>Family</div><select value={f.family} onChange={(e) => setF({ ...f, family: e.target.value })} className={inputClass}><option value={4}>IPv4</option><option value={6}>IPv6</option></select></label>
        <label><div className={labelClass}>VLAN</div><input value={f.vlan} onChange={(e) => setF({ ...f, vlan: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Usage</div><input type="number" min="0" value={f.usage} onChange={(e) => setF({ ...f, usage: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>Capacity</div><input type="number" min="1" value={f.capacity} onChange={(e) => setF({ ...f, capacity: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Site</div><input value={f.site} onChange={(e) => setF({ ...f, site: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Gateway (untuk cloud-init VM)</div><input value={f.gateway} onChange={(e) => setF({ ...f, gateway: e.target.value })} className={`${inputClass} font-mono`} placeholder="kosong = IP pertama subnet, mis. .1" data-testid="prefix-gateway" /></label>
        <label className="col-span-2 flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-xl p-3">
          <input type="checkbox" checked={f.vps_provision} onChange={(e) => setF({ ...f, vps_provision: e.target.checked })} data-testid="prefix-vps-provision" />
          <div>
            <div className="font-bold text-emerald-800 text-sm">Untuk provisioning VPS/Cloud (IP pool khusus)</div>
            <div className="text-xs text-emerald-700">Hanya prefix ber-flag ini yang dipakai alokasi IP otomatis saat auto-provision VM.</div>
          </div>
        </label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </DModal>
  );
};

/* ---- IPs ---- */
const IPsTab = () => {
  const [prefixes, setPrefixes] = useState([]);
  const [ips, setIps] = useState(null);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(null);
  const load = () => {
    api.get("/admin/dcim/prefixes").then((r) => setPrefixes(r.data));
    api.get("/admin/dcim/ips" + (filter ? `?prefix_id=${filter}` : "")).then((r) => setIps(r.data));
  };
  useEffect(() => { load(); }, [filter]); // eslint-disable-line
  if (!ips) return <div className="text-sm text-slate-500 py-10 text-center">Loading…</div>;
  const del = async (id) => { if (window.confirm("Delete IP?")) { await api.delete(`/admin/dcim/ips/${id}`); load(); } };
  return (
    <div>
      <div className="mb-4 flex items-center gap-2 justify-between">
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className={`${inputClass} max-w-xs`}>
          <option value="">All prefixes</option>
          {prefixes.map((p) => <option key={p.id} value={p.id}>{p.prefix}</option>)}
        </select>
        <button className={btnPrimary} onClick={() => setEditing("new")}>+ New IP</button>
      </div>
      {ips.length === 0 && <div className="text-center py-8 text-sm text-slate-500">No IP records - add your first below.</div>}
      {ips.length > 0 && (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr><th className="px-4 py-3 text-left">Address</th><th className="px-4 py-3 text-left">Hostname</th><th className="px-4 py-3 text-left">Role</th><th className="px-4 py-3 text-left">Customer</th><th className="px-4 py-3 text-left">Status</th><th className="px-4 py-3 text-right"></th></tr>
            </thead>
            <tbody>{ips.map((ip) => (
              <tr key={ip.id} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono">{ip.address}</td>
                <td className="px-4 py-3 text-xs">{ip.hostname || "-"}</td>
                <td className="px-4 py-3 text-xs">{ip.role || "-"}</td>
                <td className="px-4 py-3 text-xs">{ip.customer || "-"}</td>
                <td className="px-4 py-3 text-xs"><span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${ip.status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-700"}`}>{ip.status}</span></td>
                <td className="px-4 py-3 text-right">
                  <button className="text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(ip)}>Edit</button>
                  <button className="ml-3 text-slate-500 hover:text-red-600" onClick={() => del(ip.id)}>×</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
      {editing && <IPForm ip={editing === "new" ? null : editing} prefixes={prefixes} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    </div>
  );
};

const IPForm = ({ ip, prefixes, onClose, onDone }) => {
  const [f, setF] = useState({
    address: ip?.address || "", prefix_id: ip?.prefix_id || (prefixes[0]?.id || ""),
    status: ip?.status || "active", role: ip?.role || "", hostname: ip?.hostname || "",
    customer: ip?.customer || "", description: ip?.description || "",
  });
  const submit = async (e) => {
    e.preventDefault();
    if (ip) await api.put(`/admin/dcim/ips/${ip.id}`, f);
    else await api.post("/admin/dcim/ips", f);
    onDone();
  };
  return (
    <DModal title={ip ? "Edit IP" : "New IP"} onClose={onClose}>
      <form onSubmit={submit} className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Address *</div><input required value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className={`${inputClass} font-mono`} placeholder="103.28.14.42" /></label>
        <label><div className={labelClass}>Prefix</div><select value={f.prefix_id} onChange={(e) => setF({ ...f, prefix_id: e.target.value })} className={inputClass}>{prefixes.map((p) => <option key={p.id} value={p.id}>{p.prefix}</option>)}</select></label>
        <label><div className={labelClass}>Status</div><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={inputClass}><option>active</option><option>reserved</option><option>deprecated</option></select></label>
        <label><div className={labelClass}>Role</div><input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} className={inputClass} placeholder="loopback / anycast / gateway" /></label>
        <label><div className={labelClass}>Hostname</div><input value={f.hostname} onChange={(e) => setF({ ...f, hostname: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Customer</div><input value={f.customer} onChange={(e) => setF({ ...f, customer: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Description</div><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className={inputClass} /></label>
        <div className="col-span-2 flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </DModal>
  );
};

/* ---- Sites ---- */
const SitesTab = () => {
  const [rows, setRows] = useState(null);
  const [modal, setModal] = useState(false);
  const load = () => api.get("/admin/dcim/sites").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <div className="text-sm text-slate-500 py-10 text-center">Loading…</div>;
  const del = async (id) => { if (window.confirm("Delete site?")) { await api.delete(`/admin/dcim/sites/${id}`); load(); } };
  return (
    <div>
      <div className="mb-4 flex justify-end"><button className={btnPrimary} onClick={() => setModal(true)}>+ New Site</button></div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {rows.map((s) => (
          <Card key={s.id} className="p-5">
            <div className="text-sm font-extrabold text-[#0a2350]">{s.name}</div>
            <div className="text-xs font-mono text-[#f5b120] mt-1">{s.code}</div>
            <div className="text-xs text-slate-500 mt-2">{s.address}</div>
            <button onClick={() => del(s.id)} className="mt-3 text-xs text-slate-500 hover:text-red-600">Delete</button>
          </Card>
        ))}
      </div>
      {modal && <SiteForm onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
    </div>
  );
};

const SiteForm = ({ onClose, onDone }) => {
  const [f, setF] = useState({ name: "", code: "", address: "" });
  const submit = async (e) => { e.preventDefault(); await api.post("/admin/dcim/sites", f); onDone(); };
  return (
    <DModal title="New site" onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <label className="block"><div className={labelClass}>Name *</div><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={inputClass} /></label>
        <label className="block"><div className={labelClass}>Code</div><input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} className={inputClass} placeholder="JKT-METTA-5F" /></label>
        <label className="block"><div className={labelClass}>Address</div><input value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} className={inputClass} /></label>
        <div className="flex justify-end gap-2 mt-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" className={btnPrimary}>Save</button>
        </div>
      </form>
    </DModal>
  );
};

