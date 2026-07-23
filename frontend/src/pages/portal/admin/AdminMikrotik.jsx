import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import {
  Router, Server, Wifi, Activity, ShieldAlert, HardDrive, RotateCcw, Search,
  Plus, Trash2, PlayCircle, Loader2, CheckCircle2, XCircle, RefreshCw, AlertTriangle, Edit,
} from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";

const TABS = [
  { key: "devices",  label: "Devices",     icon: Server },
  { key: "bgp",      label: "BGP Peers",   icon: Wifi },
  { key: "lg",       label: "Looking Glass", icon: Search },
  { key: "bh",       label: "Blackhole",   icon: ShieldAlert },
  { key: "backup",   label: "Backup",      icon: HardDrive },
  { key: "restart",  label: "Restart",     icon: RotateCcw },
  { key: "traffic",  label: "Traffic",     icon: Activity },
];

const AdminMikrotik = () => {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [tab, setTab] = useState("devices");

  const loadDevices = () => api.get("/admin/mikrotik/devices").then((r) => {
    setDevices(r.data);
    if (!deviceId && r.data[0]) setDeviceId(r.data[0].id || "legacy");
  });
  useEffect(() => { loadDevices(); /* eslint-disable-next-line */ }, []);

  const effectiveDeviceId = deviceId === "legacy" ? "" : deviceId;

  return (
    <div>
      <PageHeader
        title="MikroTik Operations"
        subtitle="Live BGP, Looking Glass, blackhole, backup, reboot, and traffic — real RouterOS calls via librouteros. Supports multiple devices."
        actions={
          <div className="flex items-center gap-2">
            <div className={labelClass + " mr-1"}>Device:</div>
            <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className={inputClass + " h-9 py-0"} data-testid="mikrotik-device-picker">
              {devices.length === 0 && <option value="">— no devices —</option>}
              {devices.map((d) => (
                <option key={d.id || "legacy"} value={d.id || "legacy"}>
                  {d.name}{d.host ? ` · ${d.host}` : ""}
                </option>
              ))}
            </select>
          </div>
        }
      />

      <div className="flex flex-wrap gap-1 mb-5 bg-white border border-slate-200 rounded-xl p-1 w-fit">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button key={t.key} onClick={() => setTab(t.key)} data-testid={`mt-tab-${t.key}`}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 ${tab === t.key ? "bg-[#0a2350] text-white" : "text-slate-600 hover:text-[#0a2350]"}`}>
              <Icon className="h-3.5 w-3.5" /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "devices" && <DevicesTab devices={devices} reload={loadDevices} />}
      {tab === "bgp"     && <BGPTab deviceId={effectiveDeviceId} />}
      {tab === "lg"      && <LookingGlassTab deviceId={effectiveDeviceId} />}
      {tab === "bh"      && <BlackholeTab deviceId={effectiveDeviceId} />}
      {tab === "backup"  && <BackupTab deviceId={effectiveDeviceId} />}
      {tab === "restart" && <RestartTab deviceId={effectiveDeviceId} devices={devices} selectedId={deviceId} />}
      {tab === "traffic" && <TrafficTab deviceId={effectiveDeviceId} />}
    </div>
  );
};

// ---------------------------------------------- Devices tab
const DevicesTab = ({ devices, reload }) => {
  const [editing, setEditing] = useState(null);
  const [testResult, setTestResult] = useState({});

  const empty = { name: "", host: "", port: 8728, username: "", password: "", use_tls: false, site: "", notes: "" };
  const save = async (form) => {
    if (form.id) await api.put(`/admin/mikrotik/devices/${form.id}`, form);
    else         await api.post("/admin/mikrotik/devices", form);
    setEditing(null); reload();
  };
  const del = async (id) => { if (window.confirm("Delete this device?")) { await api.delete(`/admin/mikrotik/devices/${id}`); reload(); } };
  const test = async (id) => {
    setTestResult({ ...testResult, [id]: { busy: true } });
    try {
      const { data } = await api.post(`/admin/mikrotik/devices/${id}/test`);
      setTestResult({ ...testResult, [id]: data });
    } catch (e) {
      setTestResult({ ...testResult, [id]: { ok: false, message: e?.response?.data?.detail || e.message } });
    }
  };

  return (
    <div>
      <div className="flex justify-end mb-3">
        <button className={btnPrimary} onClick={() => setEditing(empty)} data-testid="mt-device-add">
          <Plus className="h-4 w-4" /> Add device
        </button>
      </div>
      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
            <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Host</th><th className="px-4 py-3 text-left">Site</th><th className="px-4 py-3 text-left">TLS</th><th className="px-4 py-3 text-left">Test</th><th className="px-4 py-3"></th></tr>
          </thead>
          <tbody>
            {devices.length === 0 && <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-400">No devices — add your first RouterOS above.</td></tr>}
            {devices.map((d) => {
              const t = testResult[d.id] || {};
              return (
                <tr key={d.id || "legacy"} className="border-t border-slate-100" data-testid={`mt-device-${d.id || "legacy"}`}>
                  <td className="px-4 py-2 font-bold text-[#0a2350]">{d.name}{d.legacy && <span className="ml-2 text-[10px] uppercase text-amber-700">legacy</span>}</td>
                  <td className="px-4 py-2 font-mono text-xs">{d.host}:{d.port}</td>
                  <td className="px-4 py-2 text-xs">{d.site || "—"}</td>
                  <td className="px-4 py-2 text-xs">{d.use_tls ? "TLS" : "plain"}</td>
                  <td className="px-4 py-2 text-xs">
                    {t.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> :
                      t.ok === true  ? <span className="text-emerald-700 font-bold">✓ {t.message}</span> :
                      t.ok === false ? <span className="text-red-700 font-bold">✗ {t.message}</span> :
                      "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {d.id && <>
                      <button className="text-xs text-[#0a2350] hover:text-[#f5b120] mr-3" onClick={() => test(d.id)} data-testid={`mt-device-test-${d.id}`}>Test</button>
                      <button className="text-xs text-[#0a2350] hover:text-[#f5b120] mr-3" onClick={() => setEditing({ ...d, password: "" })}><Edit className="h-3.5 w-3.5 inline" /></button>
                      <button className="text-xs text-red-600 hover:text-red-800" onClick={() => del(d.id)} data-testid={`mt-device-del-${d.id}`}><Trash2 className="h-3.5 w-3.5 inline" /></button>
                    </>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>

      {editing && <DeviceForm value={editing} onSave={save} onClose={() => setEditing(null)} />}
    </div>
  );
};

const DeviceForm = ({ value, onSave, onClose }) => {
  const [f, setF] = useState(value);
  const set = (k, v) => setF({ ...f, [k]: v });
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); onSave(f); }}
        className="bg-white rounded-2xl p-6 w-full max-w-lg space-y-3" data-testid="mt-device-form">
        <h3 className="text-lg font-bold text-[#0a2350]">{f.id ? "Edit device" : "Add MikroTik device"}</h3>
        <div className="grid grid-cols-2 gap-3">
          <label><div className={labelClass}>Name</div><input required value={f.name} onChange={(e) => set("name", e.target.value)} className={inputClass} data-testid="mt-device-name" /></label>
          <label><div className={labelClass}>Site (optional)</div><input value={f.site || ""} onChange={(e) => set("site", e.target.value)} className={inputClass} /></label>
          <label><div className={labelClass}>Host / IP</div><input required value={f.host} onChange={(e) => set("host", e.target.value)} className={inputClass} data-testid="mt-device-host" /></label>
          <label><div className={labelClass}>Port</div><input type="number" value={f.port} onChange={(e) => set("port", e.target.value)} className={inputClass} /></label>
          <label><div className={labelClass}>Username</div><input required value={f.username} onChange={(e) => set("username", e.target.value)} className={inputClass} data-testid="mt-device-user" /></label>
          <label><div className={labelClass}>Password {f.id && <span className="text-slate-400 font-normal">(leave blank to keep)</span>}</div><input type="password" value={f.password} onChange={(e) => set("password", e.target.value)} className={inputClass} data-testid="mt-device-pass" /></label>
          <label className="col-span-2 flex items-center gap-2"><input type="checkbox" checked={!!f.use_tls} onChange={(e) => set("use_tls", e.target.checked)} /> <span className="text-sm">Use TLS (api-ssl, port 8729)</span></label>
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="submit" className={btnPrimary} data-testid="mt-device-save">Save</button>
        </div>
      </form>
    </div>
  );
};

// ---------------------------------------------- BGP tab
const BGPTab = ({ deviceId }) => {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const load = async () => {
    setErr(""); setRows(null);
    try {
      const q = deviceId ? `?device_id=${deviceId}` : "";
      const { data } = await api.get(`/admin/mikrotik/bgp${q}`);
      setRows(data);
    } catch (e) { setErr(e?.response?.data?.detail || e.message); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [deviceId]);

  return (
    <Card className="p-0 overflow-hidden" data-testid="mt-bgp-panel">
      <div className="px-4 py-2 border-b border-slate-100 flex items-center gap-2 bg-slate-50">
        <Wifi className="h-4 w-4 text-[#0a2350]" />
        <span className="text-xs font-bold uppercase tracking-widest text-[#0a2350]">BGP peers · live</span>
        <button onClick={load} className="ml-auto text-xs text-[#0a2350] hover:text-[#f5b120]"><RefreshCw className="h-3.5 w-3.5" /></button>
      </div>
      {err && <div className="px-5 py-4 bg-red-50 text-red-700 text-sm">{err}</div>}
      {!rows && !err && <div className="p-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin inline mr-2" /> Loading…</div>}
      {rows && (
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
            <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Remote</th><th className="px-4 py-3 text-left">Remote AS</th><th className="px-4 py-3 text-left">State</th><th className="px-4 py-3 text-right">Prefixes</th><th className="px-4 py-3 text-right">Uptime</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-400">No BGP peers configured on this router.</td></tr>}
            {rows.map((p, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="px-4 py-2 font-bold text-[#0a2350]">{p.name || p[".id"]}</td>
                <td className="px-4 py-2 font-mono text-xs">{p["remote-address"] || p.remote}</td>
                <td className="px-4 py-2 font-mono text-xs">{p["remote-as"]}</td>
                <td className="px-4 py-2 uppercase text-xs font-bold text-[#f5b120]">{p.state || p.status}</td>
                <td className="px-4 py-2 text-right tabular-nums">{p["prefix-count"] || 0}</td>
                <td className="px-4 py-2 text-right text-xs text-slate-500">{p.uptime || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
};

// ---------------------------------------------- Looking Glass tab
const LookingGlassTab = ({ deviceId }) => {
  const [tool, setTool] = useState("ping");
  const [target, setTarget] = useState("8.8.8.8");
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);
  const run = async (e) => {
    e.preventDefault(); setBusy(true); setOut(null);
    try {
      const { data } = await api.post("/admin/mikrotik/looking-glass", { device_id: deviceId, tool, target });
      setOut(data);
    } catch (e) { setOut({ ok: false, error: e?.response?.data?.detail || e.message }); }
    finally { setBusy(false); }
  };
  return (
    <div>
      <Card className="p-5 mb-4">
        <form onSubmit={run} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <div>
            <div className={labelClass}>Tool</div>
            <select value={tool} onChange={(e) => setTool(e.target.value)} className={inputClass} data-testid="mt-lg-tool">
              <option value="ping">Ping (from router)</option>
              <option value="traceroute">Traceroute (from router)</option>
              <option value="bgp_route">BGP route lookup</option>
            </select>
          </div>
          <div className="md:col-span-2">
            <div className={labelClass}>Target ({tool === "bgp_route" ? "IP or prefix" : "hostname or IP"})</div>
            <input required value={target} onChange={(e) => setTarget(e.target.value)} className={inputClass} data-testid="mt-lg-target" />
          </div>
          <button className={btnPrimary} disabled={busy} data-testid="mt-lg-run">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />} Run from router
          </button>
        </form>
      </Card>
      {out && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-100 text-xs font-bold uppercase tracking-widest text-[#0a2350]">Result</div>
          <pre className="bg-slate-900 text-emerald-300 text-xs p-5 overflow-x-auto min-h-[240px] font-mono whitespace-pre-wrap" data-testid="mt-lg-output">
{out.ok === false ? `Error: ${out.error}` : JSON.stringify(out.rows, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
};

// ---------------------------------------------- Blackhole tab
const BlackholeTab = ({ deviceId }) => {
  const [rows, setRows] = useState(null);
  const [prefix, setPrefix] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = async () => {
    const q = deviceId ? `?device_id=${deviceId}` : "";
    try { const { data } = await api.get(`/admin/mikrotik/blackhole${q}`); setRows(data); }
    catch { setRows([]); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [deviceId]);
  const add = async (e) => {
    e.preventDefault(); setBusy(true); setMsg("");
    try {
      const { data } = await api.post("/admin/mikrotik/blackhole", { device_id: deviceId, prefix });
      if (data.ok === false) setMsg(data.error || "Failed");
      else { setPrefix(""); await load(); }
    } catch (e) { setMsg(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };
  const del = async (id) => {
    if (!window.confirm(`Remove blackhole route ${id}?`)) return;
    const q = deviceId ? `?device_id=${deviceId}` : "";
    await api.delete(`/admin/mikrotik/blackhole/${encodeURIComponent(id)}${q}`);
    load();
  };
  return (
    <div>
      <Card className="p-5 mb-4">
        <form onSubmit={add} className="flex items-end gap-3" data-testid="mt-bh-form">
          <label className="flex-1">
            <div className={labelClass}>Prefix to blackhole (e.g. 203.0.113.42/32)</div>
            <input required value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="203.0.113.42/32" className={`${inputClass} font-mono`} data-testid="mt-bh-prefix" />
          </label>
          <button className={btnPrimary} disabled={busy} data-testid="mt-bh-submit">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />} Announce blackhole
          </button>
        </form>
        {msg && <div className="mt-3 text-sm text-red-700">{msg}</div>}
      </Card>
      <Card className="p-0 overflow-hidden">
        <div className="px-4 py-2 border-b border-slate-100 bg-slate-50 text-xs font-bold uppercase tracking-widest text-[#0a2350]">Active blackhole routes</div>
        {!rows && <div className="p-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin inline mr-2" /> Loading…</div>}
        {rows && (
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
              <tr><th className="px-4 py-3 text-left">Prefix</th><th className="px-4 py-3 text-left">Distance</th><th className="px-4 py-3 text-left">Comment</th><th className="px-4 py-3"></th></tr>
            </thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={4} className="px-4 py-10 text-center text-slate-400">No blackhole routes on this device.</td></tr>}
              {rows.map((r) => (
                <tr key={r[".id"]} className="border-t border-slate-100">
                  <td className="px-4 py-2 font-mono text-xs font-bold">{r["dst-address"]}</td>
                  <td className="px-4 py-2">{r.distance}</td>
                  <td className="px-4 py-2 text-xs text-slate-600">{r.comment || "—"}</td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => del(r[".id"])} className="text-xs text-red-600 hover:text-red-800">
                      <Trash2 className="h-3 w-3 inline" /> Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
};

// ---------------------------------------------- Backup tab
const BackupTab = ({ deviceId }) => {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = async () => {
    const q = deviceId ? `?device_id=${deviceId}` : "";
    try { const { data } = await api.get(`/admin/mikrotik/backups${q}`); setRows(data); }
    catch { setRows([]); }
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [deviceId]);
  const create = async () => {
    setBusy(true); setMsg("");
    try {
      const { data } = await api.post("/admin/mikrotik/backups", { device_id: deviceId });
      if (data.ok === false) setMsg(data.error || "Failed"); else setMsg(`Backup queued: ${data.name}`);
      await load();
    } catch (e) { setMsg(e?.response?.data?.detail || e.message); }
    finally { setBusy(false); }
  };
  const del = async (name) => {
    if (!window.confirm(`Delete ${name} from router?`)) return;
    const q = deviceId ? `?device_id=${deviceId}` : "";
    await api.delete(`/admin/mikrotik/backups/${encodeURIComponent(name)}${q}`); load();
  };
  return (
    <div>
      <div className="flex justify-between items-center mb-3">
        <div className="text-xs text-slate-500">Backups saved on the router's local disk (<span className="font-mono">/system/backup</span>).</div>
        <button onClick={create} disabled={busy} className={btnPrimary} data-testid="mt-backup-create">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <HardDrive className="h-4 w-4" />} New backup
        </button>
      </div>
      {msg && <div className="mb-3 text-sm bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-lg px-3 py-2">{msg}</div>}
      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
            <tr><th className="px-4 py-3 text-left">Name</th><th className="px-4 py-3 text-left">Type</th><th className="px-4 py-3 text-left">Created</th><th className="px-4 py-3 text-right">Size</th><th className="px-4 py-3"></th></tr>
          </thead>
          <tbody>
            {!rows && <tr><td colSpan={5} className="px-4 py-8 text-center text-slate-400"><Loader2 className="h-4 w-4 animate-spin inline mr-2" /> Loading…</td></tr>}
            {rows && rows.length === 0 && <tr><td colSpan={5} className="px-4 py-10 text-center text-slate-400">No backups on this device yet.</td></tr>}
            {rows && rows.map((f) => (
              <tr key={f.name} className="border-t border-slate-100">
                <td className="px-4 py-2 font-mono text-xs font-bold">{f.name}</td>
                <td className="px-4 py-2 text-xs uppercase">{f.type || "backup"}</td>
                <td className="px-4 py-2 text-xs text-slate-500">{f["creation-time"] || "—"}</td>
                <td className="px-4 py-2 text-right tabular-nums">{f.size ? `${Math.round(f.size / 1024)} KB` : "—"}</td>
                <td className="px-4 py-2 text-right"><button onClick={() => del(f.name)} className="text-xs text-red-600 hover:text-red-800"><Trash2 className="h-3 w-3 inline" /> Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};

// ---------------------------------------------- Restart tab
const RestartTab = ({ deviceId, devices, selectedId }) => {
  const [confirmText, setConfirmText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const selected = devices.find((d) => (d.id || "legacy") === selectedId);
  const reboot = async () => {
    if (confirmText !== "REBOOT") return;
    if (!window.confirm(`Reboot ${selected?.name || "device"} now? Router will be offline ~30-60s.`)) return;
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.post("/admin/mikrotik/reboot", { device_id: deviceId, confirm: "REBOOT" });
      setMsg(data);
    } catch (e) { setMsg({ ok: false, error: e?.response?.data?.detail || e.message }); }
    finally { setBusy(false); setConfirmText(""); }
  };
  return (
    <Card className="p-6 max-w-lg" data-testid="mt-restart-panel">
      <div className="flex items-start gap-3 mb-4">
        <AlertTriangle className="h-6 w-6 text-red-600 mt-0.5" />
        <div>
          <h3 className="text-base font-bold text-[#0a2350]">Reboot RouterOS</h3>
          <p className="text-xs text-slate-600 mt-1">This will send <span className="font-mono">/system/reboot</span> to <b>{selected?.name || "the selected device"}</b>. Traffic will be interrupted for 30–60 seconds. Requires typing <b>REBOOT</b> to confirm.</p>
        </div>
      </div>
      <label>
        <div className={labelClass}>Type REBOOT to confirm</div>
        <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} className={`${inputClass} font-mono`} placeholder="REBOOT" data-testid="mt-restart-confirm" />
      </label>
      <button onClick={reboot} disabled={busy || confirmText !== "REBOOT"} className={`${btnPrimary} bg-red-600 hover:bg-red-700 mt-4 ${confirmText !== "REBOOT" ? "opacity-40" : ""}`} data-testid="mt-restart-btn">
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />} Reboot now
      </button>
      {msg && (
        <div className={`mt-4 rounded-lg px-3 py-2 text-sm border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-red-50 border-red-200 text-red-700"}`}>
          {msg.ok ? `✓ ${msg.message}` : `✗ ${msg.error}`}
        </div>
      )}
    </Card>
  );
};

// ---------------------------------------------- Traffic tab (live graph)
const TrafficTab = ({ deviceId }) => {
  const [interfaces, setInterfaces] = useState([]);
  const [iface, setIface] = useState("");
  const [series, setSeries] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const q = deviceId ? `?device_id=${deviceId}` : "";
    api.get(`/admin/mikrotik/interfaces${q}`).then((r) => {
      setInterfaces(r.data);
      if (r.data[0]) setIface(r.data[0].name || r.data[0][".id"]);
    }).catch(() => setInterfaces([]));
    setSeries([]);
  }, [deviceId]);

  useEffect(() => {
    if (!iface) return;
    let stopped = false;
    setSeries([]); setErr("");
    const tick = async () => {
      if (stopped) return;
      try {
        const q = `?device_id=${deviceId || ""}&interface=${encodeURIComponent(iface)}`;
        const { data } = await api.get(`/admin/mikrotik/traffic${q}`);
        const rx = Number(data["rx-bits-per-second"] || data.rx || 0);
        const tx = Number(data["tx-bits-per-second"] || data.tx || 0);
        setSeries((prev) => {
          const next = [...prev, { t: new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" }), rx, tx }];
          return next.slice(-30);
        });
      } catch (e) { setErr(e?.response?.data?.detail || e.message); }
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => { stopped = true; clearInterval(id); };
  }, [iface, deviceId]);

  const fmt = (bps) => bps >= 1e9 ? `${(bps/1e9).toFixed(2)} Gbps` : bps >= 1e6 ? `${(bps/1e6).toFixed(2)} Mbps` : bps >= 1e3 ? `${(bps/1e3).toFixed(1)} kbps` : `${bps} bps`;
  const cur = series[series.length - 1] || { rx: 0, tx: 0 };

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-4 items-end">
        <div className="flex-1 max-w-xs">
          <div className={labelClass}>Interface</div>
          <select value={iface} onChange={(e) => setIface(e.target.value)} className={inputClass} data-testid="mt-traffic-iface">
            <option value="">— pick —</option>
            {interfaces.map((it, i) => <option key={i} value={it.name || it[".id"]}>{it.name || it[".id"]}</option>)}
          </select>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 px-4 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold">RX (in)</div>
          <div className="text-lg font-extrabold text-emerald-700 tabular-nums" data-testid="mt-traffic-rx">{fmt(cur.rx)}</div>
        </div>
        <div className="rounded-xl bg-white border border-slate-200 px-4 py-2">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 font-bold">TX (out)</div>
          <div className="text-lg font-extrabold text-[#0a2350] tabular-nums" data-testid="mt-traffic-tx">{fmt(cur.tx)}</div>
        </div>
      </div>
      {err && <Card className="p-3 mb-3 bg-red-50 text-red-700 text-sm">{err}</Card>}
      <Card className="p-4">
        <div style={{ width: "100%", height: 300 }}>
          <ResponsiveContainer>
            <LineChart data={series} margin={{ top: 6, right: 20, bottom: 0, left: -10 }}>
              <CartesianGrid stroke="#eef1f5" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="t" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={fmt} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v) => fmt(v)} contentStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="rx" name="RX" stroke="#16a34a" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="tx" name="TX" stroke="#0a2350" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="text-[11px] text-slate-500 mt-2">Sampled every 3 seconds via <span className="font-mono">/interface/monitor-traffic</span>. Keeps a rolling window of 30 samples (~90s).</div>
      </Card>
    </div>
  );
};

export default AdminMikrotik;
