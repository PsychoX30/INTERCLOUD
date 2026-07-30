import React, { useState, useEffect } from "react";
import { PageHeader, Card, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { TerminalSquare, Loader2, Globe, Server } from "lucide-react";
import { api } from "../../../portal/api";

/* -------------------- Provisioning (cPanel / Plesk / Proxmox) -------------------- */
export const AdminProvisioning = () => {
  const [tab, setTab] = useState("flow");
  return (
    <div>
      <PageHeader title="Provisioning" subtitle="Order-to-VM lifecycle: verify payment → provision hosting or VM automatically." />
      <div className="flex flex-wrap gap-2 border-b border-slate-200 mb-4">
        {[["flow", "Order → Payment → Deploy"], ["cpanel", "cPanel/WHM"], ["plesk", "Plesk"], ["proxmox", "Proxmox VE"]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 h-11 -mb-px border-b-2 text-sm font-bold ${tab === k ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500"}`}>{l}</button>
        ))}
      </div>
      {tab === "flow" && <FlowDiagram />}
      {tab === "cpanel" && <ProvisionForm module="cPanel" fields={[["username", "Cust Username"], ["domain", "Primary Domain"], ["plan", "Package Plan"], ["password", "Initial Password", "password"]]} />}
      {tab === "plesk" && <ProvisionForm module="Plesk" fields={[["username", "Login"], ["domain", "Domain"], ["plan", "Service Plan"], ["password", "Password", "password"]]} />}
      {tab === "proxmox" && <ProxmoxProvision />}
    </div>
  );
};

const FlowDiagram = () => (
  <Card className="p-8">
    <div className="grid md:grid-cols-4 gap-4 relative">
      {[
        { n: "01", t: "Client Order", d: "Client picks a product in the portal and submits an order." },
        { n: "02", t: "Payment Verified", d: "Manual bank-transfer confirmation OR automatic webhook from Duitku/Xendit/Midtrans." },
        { n: "03", t: "Auto Provision", d: "cPanel account, Plesk domain, or Proxmox VM is created via module API." },
        { n: "04", t: "Client Handover", d: "Connection details + credentials pushed to client dashboard + email." },
      ].map((s, i, arr) => (
        <div key={s.n} className="relative">
          <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <div className="h-9 w-9 rounded-full bg-[#f5b120] text-[#0a2350] text-xs font-extrabold flex items-center justify-center">{s.n}</div>
            <div className="mt-3 font-extrabold text-[#0a2350]">{s.t}</div>
            <p className="mt-2 text-sm text-slate-600 leading-relaxed">{s.d}</p>
          </div>
          {i < arr.length - 1 && <div className="hidden md:block absolute top-1/2 -right-2 w-4 h-px bg-[#f5b120]/40" />}
        </div>
      ))}
    </div>
  </Card>
);

const ProxmoxProvision = () => {
  const [os, setOs] = useState([]);
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);
  const [f, setF] = useState({ hostname: "", cores: 2, memory: 2048, disk: 40, node: "" });
  const [reqOpen, setReqOpen] = useState(false);
  const [tplInfo, setTplInfo] = useState(null);

  useEffect(() => { api.get("/admin/proxmox/os-templates").then((r) => setOs(r.data)); }, []);
  useEffect(() => {
    api.get("/admin/proxmox/templates")
      .then((r) => setTplInfo(r.data))
      .catch((e) => setTplInfo({ error: e?.response?.data?.detail || "Integrasi Proxmox belum aktif" }));
  }, []);

  const run = async (e) => {
    e.preventDefault(); setBusy(true); setMsg(null); setErr(null);
    try {
      const { data } = await api.post("/admin/provisioning/proxmox/create", {
        hostname: f.hostname, node: f.node, os: chosen,
        cores: f.cores, memory: f.memory, disk: f.disk,
      });
      setMsg(`✓ VM "${data.name}" (VMID ${data.vmid}) berhasil dibuat di node ${data.node}.`);
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
            <div className={labelClass}>OS Template - from Proxmox ISO library</div>
            <button type="button" className="text-xs font-bold text-[#f5b120] hover:text-[#0a2350]" onClick={() => setReqOpen(true)}>OS not listed? Request one →</button>
          </div>
          <div className="rounded-xl border border-slate-200 max-h-56 overflow-y-auto divide-y divide-slate-100">
            {Object.keys(groupedOs).length === 0 && <div className="p-4 text-sm text-slate-500">Loading templates…</div>}
            {Object.entries(groupedOs).map(([fam, list]) => (
              <div key={fam}>
                <div className="px-3 py-1.5 text-[10px] uppercase tracking-widest font-bold text-slate-500 bg-slate-50">{fam}</div>
                {list.map((t) => (
                  <button
                    key={t.name}
                    type="button"
                    onClick={() => setChosen(t.name)}
                    className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between ${chosen === t.name ? "bg-[#f5b120]/15 text-[#0a2350] font-bold" : "hover:bg-slate-50"}`}
                    data-testid={`os-${t.name}`}
                  >
                    <span>{t.name}</span>
                    <span className="text-[10px] uppercase tracking-widest text-slate-400">{t.type}</span>
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
              <td className="px-4 py-3 font-mono">{p.prefix}</td>
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

