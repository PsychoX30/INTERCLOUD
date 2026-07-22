import React, { useState, useEffect } from "react";
import { PageHeader, Card, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Terminal, TerminalSquare, Loader2, Globe, Server, Router, ShieldAlert } from "lucide-react";
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
  const [f, setF] = useState({ hostname: "", cores: 2, memory: 2048, disk: 40, node: "prox-jkt-05" });
  const [reqOpen, setReqOpen] = useState(false);

  useEffect(() => { api.get("/admin/proxmox/os-templates").then((r) => setOs(r.data)); }, []);

  const run = (e) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    setTimeout(() => { setBusy(false); setMsg(`✓ Proxmox job queued for VM "${f.hostname}" running ${chosen} on ${f.node} (mock). Configure Proxmox creds under Integrations to run for real.`); }, 900);
  };

  const groupedOs = os.reduce((acc, t) => { (acc[t.family] = acc[t.family] || []).push(t); return acc; }, {});

  return (
    <Card className="p-6">
      <form onSubmit={run} className="grid grid-cols-2 gap-3">
        <label><div className={labelClass}>VM Hostname *</div><input required value={f.hostname} onChange={(e) => setF({ ...f, hostname: e.target.value })} className={inputClass} placeholder="app-prod-01" data-testid="prov-hostname" /></label>
        <label><div className={labelClass}>Target Node</div><input value={f.node} onChange={(e) => setF({ ...f, node: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>vCPU</div><input type="number" min="1" value={f.cores} onChange={(e) => setF({ ...f, cores: e.target.value })} className={inputClass} /></label>
        <label><div className={labelClass}>RAM (MB)</div><input type="number" min="512" value={f.memory} onChange={(e) => setF({ ...f, memory: e.target.value })} className={inputClass} /></label>
        <label className="col-span-2"><div className={labelClass}>Disk (GB)</div><input type="number" min="10" value={f.disk} onChange={(e) => setF({ ...f, disk: e.target.value })} className={inputClass} /></label>

        <div className="col-span-2">
          <div className="flex items-center justify-between mb-2">
            <div className={labelClass}>OS Template — from Proxmox ISO library</div>
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
      {msg && <div className="mt-4 text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-2">{msg}</div>}

      <div className="mt-6">
        <div className={labelClass}>noVNC Console (mock)</div>
        <div className="mt-2 rounded-xl bg-black h-56 flex items-center justify-center text-emerald-400 font-mono text-xs relative overflow-hidden">
          <div className="absolute inset-0 opacity-40 pointer-events-none" style={{ backgroundImage: "linear-gradient(rgba(0,255,0,0.05) 1px, transparent 1px)", backgroundSize: "100% 3px" }} />
          <pre className="relative text-left leading-relaxed">
{`[    0.000000] Booting ${chosen || "OS"}...
[    1.412001] systemd[1]: Started system boot.
[  ok  ] Reached target Cloud-init target.
${(f.hostname || "vm-hostname")} login: _`}
          </pre>
        </div>
      </div>

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

const ProvisionForm = ({ module, fields, withConsole }) => {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [f, setF] = useState({});
  const run = (e) => {
    e.preventDefault(); setBusy(true); setMsg(null);
    setTimeout(() => { setBusy(false); setMsg(`✓ ${module} provisioning job queued (mock). Configure real credentials in Integrations to run against your server.`); }, 900);
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
      {msg && <div className="mt-4 text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-2">{msg}</div>}
      {withConsole && (
        <div className="mt-6">
          <div className={labelClass}>noVNC Console (mock)</div>
          <div className="mt-2 rounded-xl bg-black h-64 flex items-center justify-center text-emerald-400 font-mono text-xs relative overflow-hidden">
            <div className="absolute inset-0 opacity-40 pointer-events-none" style={{ backgroundImage: "linear-gradient(rgba(0,255,0,0.05) 1px, transparent 1px)", backgroundSize: "100% 3px" }} />
            <pre className="relative text-left leading-relaxed">
{`[    0.000000] Booting Ubuntu 22.04 LTS
[    0.014215] Initializing cgroup subsys cpuset
[    0.030918] Linux version 5.15.0-generic
[    1.412001] systemd[1]: Started Update UTMP about System Boot/Shutdown.
[  ok  ] Reached target Cloud-init target.

vm-hostname login: _`}
            </pre>
          </div>
        </div>
      )}
    </Card>
  );
};

/* -------------------- MikroTik Ops -------------------- */
export const AdminMikrotik = () => {
  const [tab, setTab] = useState("lg");
  return (
    <div>
      <PageHeader title="MikroTik Operations" subtitle="Live BGP net-mon, Looking Glass, blackhole, backup, restart, and traffic graphs." />
      <div className="flex flex-wrap gap-2 border-b border-slate-200 mb-4">
        {[["lg", "Looking Glass"], ["bgp", "BGP Monitor"], ["bh", "Blackhole"], ["backup", "Backup"], ["restart", "Restart"], ["traffic", "Traffic"]].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 h-11 -mb-px border-b-2 text-sm font-bold ${tab === k ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500"}`}>{l}</button>
        ))}
      </div>
      {tab === "lg" && <LookingGlass />}
      {tab === "bgp" && <BGPMonitor />}
      {tab === "bh" && <Blackhole />}
      {tab === "backup" && <MikroBackup />}
      {tab === "restart" && <MikroRestart />}
      {tab === "traffic" && <MikroTraffic />}
    </div>
  );
};

const LookingGlass = () => {
  const [cmd, setCmd] = useState("ping"); const [target, setTarget] = useState("8.8.8.8"); const [out, setOut] = useState(""); const [busy, setBusy] = useState(false);
  const run = (e) => {
    e.preventDefault(); setBusy(true); setOut("");
    setTimeout(() => {
      const t = { ping: `PING ${target}: 56 data bytes\n64 bytes from ${target}: seq=0 ttl=118 time=12.4 ms\n64 bytes from ${target}: seq=1 ttl=118 time=11.9 ms\n64 bytes from ${target}: seq=2 ttl=118 time=12.1 ms\n\n--- ${target} ping statistics ---\n3 packets transmitted, 3 packets received, 0% packet loss\nround-trip min/avg/max = 11.9/12.1/12.4 ms`,
        traceroute: `traceroute to ${target}, 30 hops max\n 1  gw.icd-cust.net   0.5 ms\n 2  10.10.0.1         1.2 ms\n 3  218.100.36.1      3.1 ms  (APJII IIX)\n 4  74.125.243.129    8.4 ms  (Google Edge)\n 5  ${target}         12.1 ms`,
        bgp_route: `Route to ${target}:\n  AS Path: 12345 15169\n  Next Hop: 218.100.36.1 (APJII IIX)\n  Origin: IGP\n  Local Pref: 100\n  MED: 50\n  Communities: 12345:100 12345:2000` };
      setOut(t[cmd]); setBusy(false);
    }, 700);
  };
  return (
    <Card className="p-6">
      <form onSubmit={run} className="flex items-end gap-2 flex-wrap">
        <label className="flex-1 min-w-[180px]">
          <div className={labelClass}>Target</div>
          <input value={target} onChange={(e) => setTarget(e.target.value)} className={inputClass} required data-testid="lg-target" />
        </label>
        <label>
          <div className={labelClass}>Command</div>
          <select value={cmd} onChange={(e) => setCmd(e.target.value)} className={inputClass} data-testid="lg-cmd">
            <option value="ping">Ping</option><option value="traceroute">Traceroute</option><option value="bgp_route">BGP Route</option>
          </select>
        </label>
        <button className={btnPrimary} disabled={busy} data-testid="lg-run">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Terminal className="h-4 w-4" />} Run</button>
      </form>
      <pre className="mt-5 bg-slate-900 text-emerald-300 text-xs p-4 rounded-xl overflow-x-auto min-h-[240px] font-mono">{out || "// Output will appear here"}</pre>
    </Card>
  );
};

const BGPMonitor = () => (
  <Card className="p-6">
    <div className="grid sm:grid-cols-3 gap-3 mb-5">
      {[["Peers Established", "8/8", "good"], ["Prefixes IPv4", "894,231", "default"], ["Prefixes IPv6", "184,502", "default"], ["Route Server APJII", "up", "good"], ["MED Anomaly", "0", "good"], ["Route Flaps (5m)", "3", "warn"]].map(([l, v, t]) => (
        <div key={l} className={`rounded-xl border p-3 ${t === "good" ? "border-emerald-200 bg-emerald-50" : t === "warn" ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-slate-50"}`}>
          <div className="text-[10px] uppercase font-bold text-slate-500 tracking-widest">{l}</div>
          <div className="text-lg font-extrabold text-[#0a2350]">{v}</div>
        </div>
      ))}
    </div>
    <table className="w-full min-w-[720px] text-sm">
      <thead className="text-xs uppercase tracking-widest text-slate-500 border-b border-slate-200"><tr><th className="text-left py-2">Neighbor</th><th className="text-left">AS</th><th className="text-left">Uptime</th><th className="text-right">Prefixes</th><th className="text-left">State</th></tr></thead>
      <tbody>
        {[["218.100.36.1", "APJII IIX", "12d 4h", "580,432", "Established"], ["103.28.14.1", "OPENIXP", "8d 22h", "244,110", "Established"], ["185.100.20.5", "SGIX", "3d 5h", "22,340", "Established"], ["1.1.1.1", "Cloudflare", "45d", "40,120", "Established"]].map((r) => (
          <tr key={r[0]} className="border-b border-slate-100"><td className="py-2 font-mono">{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td className="text-right">{r[3]}</td><td><span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-100 text-emerald-700 font-bold">{r[4]}</span></td></tr>
        ))}
      </tbody>
    </table>
  </Card>
);

const Blackhole = () => {
  const [ip, setIp] = useState(""); const [rows, setRows] = useState([{ prefix: "103.28.14.50/32", added: "2h ago", by: "admin" }]);
  const add = (e) => { e.preventDefault(); setRows([{ prefix: `${ip}/32`, added: "just now", by: "you" }, ...rows]); setIp(""); };
  return (
    <Card className="p-6">
      <form onSubmit={add} className="flex items-end gap-2 mb-4"><label className="flex-1"><div className={labelClass}>IP / Prefix to blackhole</div><input required value={ip} onChange={(e) => setIp(e.target.value)} placeholder="103.28.14.42" className={inputClass} /></label><button className={btnPrimary}><ShieldAlert className="h-4 w-4" /> Announce blackhole</button></form>
      <table className="w-full min-w-[720px] text-sm"><thead className="text-xs uppercase tracking-widest text-slate-500 border-b border-slate-200"><tr><th className="text-left py-2">Prefix</th><th className="text-left">Added</th><th className="text-left">By</th></tr></thead>
        <tbody>{rows.map((r) => (<tr key={r.prefix + r.added} className="border-b border-slate-100"><td className="py-2 font-mono">{r.prefix}</td><td>{r.added}</td><td>{r.by}</td></tr>))}</tbody>
      </table>
    </Card>
  );
};

const MikroBackup = () => (
  <Card className="p-6">
    <p className="text-sm text-slate-600 mb-4">Latest backups from all managed routers (mock).</p>
    <table className="w-full min-w-[720px] text-sm"><thead className="text-xs uppercase tracking-widest text-slate-500 border-b border-slate-200"><tr><th className="text-left py-2">Router</th><th className="text-left">Backup At</th><th className="text-right">Size</th><th className="text-right">Action</th></tr></thead>
      <tbody>{[["RTR-JKT-CORE-01", "Today 03:00", "184 KB"], ["RTR-JKT-CORE-02", "Today 03:00", "182 KB"], ["RTR-BDG-EDGE-01", "Today 03:00", "156 KB"]].map((r) => (<tr key={r[0]} className="border-b border-slate-100"><td className="py-2 font-bold text-[#0a2350]">{r[0]}</td><td>{r[1]}</td><td className="text-right">{r[2]}</td><td className="text-right"><button className="text-[#f5b120] text-xs font-bold">Download</button></td></tr>))}</tbody>
    </table>
  </Card>
);

const MikroRestart = () => (
  <Card className="p-6">
    <p className="text-sm text-slate-600 mb-4">Reboot or reload a managed router (mock).</p>
    <div className="space-y-2">
      {["RTR-JKT-CORE-01", "RTR-JKT-CORE-02", "RTR-BDG-EDGE-01"].map((r) => (
        <div key={r} className="flex items-center justify-between rounded-xl bg-slate-50 border border-slate-200 px-4 py-3">
          <div><div className="font-bold text-[#0a2350]">{r}</div><div className="text-xs text-slate-500">Uptime: 12 days 4 hours</div></div>
          <div className="flex gap-2"><button className={btnSecondary}>Soft reload</button><button className={btnPrimary}>Reboot</button></div>
        </div>
      ))}
    </div>
  </Card>
);

const MikroTraffic = () => (
  <Card className="p-6">
    <p className="text-sm text-slate-600 mb-4">Interface-level traffic monitor (mock — wire to SNMP via MikroTik integration to serve live data).</p>
    <div className="grid sm:grid-cols-2 gap-3">
      {[["ether1 · WAN APJII", 640, 512], ["ether2 · WAN OpenIXP", 280, 194], ["sfp1 · CoreLink", 1120, 890], ["bridge · Customer VLANs", 940, 720]].map(([n, i, o]) => (
        <div key={n} className="rounded-xl bg-slate-50 border border-slate-200 p-4">
          <div className="text-sm font-bold text-[#0a2350]">{n}</div>
          <div className="mt-1 flex items-center gap-2 text-xs"><span className="text-emerald-600 font-bold">↓ {i} Mbps</span><span className="text-blue-600 font-bold">↑ {o} Mbps</span></div>
          <div className="mt-2 h-2 bg-slate-200 rounded overflow-hidden"><div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, i / 15)}%` }} /></div>
          <div className="mt-1 h-2 bg-slate-200 rounded overflow-hidden"><div className="h-full bg-blue-500" style={{ width: `${Math.min(100, o / 15)}%` }} /></div>
        </div>
      ))}
    </div>
  </Card>
);

/* -------------------- DCIM & IPAM (native, live, editable) -------------------- */
export const AdminDCIM = () => {
  const [tab, setTab] = useState("racks");
  return (
    <div>
      <PageHeader title="DCIM & IPAM" subtitle="Live, editable rack and IP address management — inspired by NetBox but native to this console." />
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
        <label className="col-span-2"><div className={labelClass}>Site</div><input value={f.site} onChange={(e) => setF({ ...f, site: e.target.value })} className={inputClass} placeholder="Cyber 1 — Metta" /></label>
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
    <DModal title={`Occupancy — ${rack.name}`} onClose={onClose}>
      <div className="space-y-2 max-h-60 overflow-y-auto mb-3">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-2 rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-sm">
            <span className="font-mono w-20 text-xs">U{r.u_bot}–U{r.u_top}</span>
            <span className="flex-1 truncate font-semibold text-[#0a2350]">{r.label}</span>
            <span className="text-xs text-slate-500">{r.customer || "—"}</span>
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
                <div className="flex items-center gap-2">
                  <div className="h-1.5 w-24 bg-slate-100 rounded overflow-hidden"><div className="h-full bg-[#0a2350]" style={{ width: `${Math.min(100, (p.usage / p.capacity) * 100)}%` }} /></div>
                  <span className="text-xs">{p.usage} / {p.capacity}</span>
                </div>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-slate-500">{p.vlan}</td>
              <td className="px-4 py-3">{p.site}</td>
              <td className="px-4 py-3 text-right">
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
      {ips.length === 0 && <div className="text-center py-8 text-sm text-slate-500">No IP records — add your first below.</div>}
      {ips.length > 0 && (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr><th className="px-4 py-3 text-left">Address</th><th className="px-4 py-3 text-left">Hostname</th><th className="px-4 py-3 text-left">Role</th><th className="px-4 py-3 text-left">Customer</th><th className="px-4 py-3 text-left">Status</th><th className="px-4 py-3 text-right"></th></tr>
            </thead>
            <tbody>{ips.map((ip) => (
              <tr key={ip.id} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono">{ip.address}</td>
                <td className="px-4 py-3 text-xs">{ip.hostname || "—"}</td>
                <td className="px-4 py-3 text-xs">{ip.role || "—"}</td>
                <td className="px-4 py-3 text-xs">{ip.customer || "—"}</td>
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

/* -------------------- Diagnostics -------------------- */
export const AdminDiagnostics = () => {
  const [tool, setTool] = useState("ping"); const [target, setTarget] = useState("8.8.8.8"); const [out, setOut] = useState(""); const [busy, setBusy] = useState(false);
  const run = (e) => {
    e.preventDefault(); setBusy(true); setOut("");
    setTimeout(() => {
      const m = {
        ping: `PING ${target}\n64 bytes seq=0 ttl=118 time=12.4 ms\n64 bytes seq=1 ttl=118 time=11.9 ms\n64 bytes seq=2 ttl=118 time=12.1 ms\n\nPacket loss: 0%  Avg RTT: 12.1 ms`,
        traceroute: `traceroute to ${target}\n 1  gw.icd 0.5ms\n 2  218.100.36.1 3.1ms (APJII)\n 3  74.125.243.129 8.4ms (Google Edge)\n 4  ${target} 12.1ms`,
        nslookup: `Non-authoritative answer:\nName:    ${target}\nAddress: 172.217.194.113\nAddress: 2404:6800:4003:c07::71`,
        whois: `Domain Name: ${target.toUpperCase()}\nRegistrar: Namecheap Inc.\nCreation Date: 2010-04-13\nExpiration Date: 2027-04-13\nName Servers: NS1.CLOUDFLARE.COM, NS2.CLOUDFLARE.COM`,
        blacklist: `Checking ${target} across 34 DNSBLs...\n\n ✓ SPAMHAUS-SBL      clean\n ✓ SPAMHAUS-XBL      clean\n ✓ BARRACUDA         clean\n ✓ SORBS             clean\n ✓ CBL               clean\n ⚠ UCEPROTECT-3      listed (soft)\n\nOverall: mostly clean`,
      };
      setOut(m[tool]); setBusy(false);
    }, 700);
  };
  return (
    <div>
      <PageHeader title="Diagnostic Tools" subtitle="Ping, traceroute, nslookup, whois, and blacklist checks — from Intercloud's network vantage point." />
      <Card className="p-6">
        <form onSubmit={run} className="flex flex-wrap items-end gap-2">
          <label className="flex-1 min-w-[220px]"><div className={labelClass}>Target (IP or Domain)</div><input required value={target} onChange={(e) => setTarget(e.target.value)} className={inputClass} data-testid="diag-target" /></label>
          <label><div className={labelClass}>Tool</div>
            <select value={tool} onChange={(e) => setTool(e.target.value)} className={inputClass} data-testid="diag-tool">
              <option value="ping">Ping</option><option value="traceroute">Traceroute</option><option value="nslookup">nslookup</option><option value="whois">WHOIS</option><option value="blacklist">Blacklist Check</option>
            </select>
          </label>
          <button className={btnPrimary} disabled={busy} data-testid="diag-run">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <TerminalSquare className="h-4 w-4" />} Run</button>
        </form>
        <pre className="mt-5 bg-slate-900 text-emerald-300 text-xs p-4 rounded-xl overflow-x-auto min-h-[240px] font-mono">{out || "// Output will appear here"}</pre>
      </Card>
    </div>
  );
};

/* -------------------- Add-ons (coming soon skeleton) -------------------- */
export const AdminAddons = () => (
  <div>
    <PageHeader title="Product Add-ons" subtitle="Attach optional extras to any base product — extra IPv4, DDoS protection, weekly backups, control panel license." />
    <Card className="p-6">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="text-xs uppercase tracking-widest text-slate-500 border-b border-slate-200"><tr><th className="text-left py-2">Add-on</th><th className="text-left">Category</th><th className="text-right">Monthly</th><th className="text-left">Attached to</th></tr></thead>
        <tbody>{[
          ["Extra IPv4", "network", "Rp 50.000", "VPS · Dedicated"],
          ["DDoS Protection Basic", "security", "Rp 250.000", "All"],
          ["Weekly Backup", "backup", "Rp 100.000", "Hosting · VPS"],
          ["cPanel License (Solo)", "license", "Rp 220.000", "VPS · Dedicated"],
          ["Managed OS", "managed", "Rp 500.000", "VPS · Dedicated"],
        ].map((r, i) => (<tr key={i} className="border-b border-slate-100"><td className="py-2 font-bold text-[#0a2350]">{r[0]}</td><td className="uppercase text-xs font-bold text-[#f5b120]">{r[1]}</td><td className="text-right font-semibold">{r[2]}</td><td className="text-xs text-slate-500">{r[3]}</td></tr>))}</tbody>
      </table>
      <p className="mt-4 text-[11px] text-slate-500">Full CRUD coming next — model already lives on the backend.</p>
    </Card>
  </div>
);

/* -------------------- Email Campaigns -------------------- */
export const AdminEmailCampaigns = () => (
  <div>
    <PageHeader title="Email & Campaigns" subtitle="Automated newsletters, invoice reminders, and order confirmations." />
    <div className="grid sm:grid-cols-3 gap-4">
      {[
        ["Overdue Reminder", "runs daily", "18 recipients"],
        ["Renewal Notice", "T-14, T-7, T-1", "42 recipients"],
        ["Welcome Email", "on signup", "instant"],
        ["Order Confirmation", "on order", "instant"],
        ["Monthly Newsletter", "1st of month", "opt-in list"],
        ["Maintenance Alert", "on-demand", "affected clients"],
      ].map(([n, sched, aud]) => (
        <Card key={n} className="p-5">
          <div className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">{sched}</div>
          <div className="text-lg font-extrabold text-[#0a2350]">{n}</div>
          <div className="text-xs text-slate-500 mt-1">{aud}</div>
          <div className="mt-4 flex gap-2">
            <button className={btnSecondary}>Edit template</button>
          </div>
        </Card>
      ))}
    </div>
    <p className="mt-4 text-[11px] text-slate-500">Uses your SMTP integration; add it under <b>Integrations</b> to go live.</p>
  </div>
);
