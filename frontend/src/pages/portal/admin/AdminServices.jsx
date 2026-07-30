import React, { useEffect, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, Card, StatusBadge } from "../ui";
import { DataTable } from "../../../components/ui/data-table";

const AdminServices = () => {
  const [rows, setRows] = useState(null);
  const [users, setUsers] = useState({});
  const [active, setActive] = useState(null);
  useEffect(() => {
    api.get("/admin/services").then((r) => setRows(r.data));
    api.get("/admin/users").then((r) => {
      const map = {};
      for (const u of r.data) map[u.id] = u;
      setUsers(map);
    }).catch(() => {});
  }, []);

  const columns = [
    { key: "product_name", label: "Service", sortable: true,
      render: (_v, s) => (
        <>
          <div className="font-semibold text-[#0a2350]">{s.product_name}</div>
          <div className="text-xs text-slate-500">{s.name}</div>
        </>
      ) },
    { key: "category", label: "Category", sortable: true,
      render: (v) => <span className="uppercase text-xs font-bold text-[#f5b120]">{v}</span> },
    { key: "user_id", label: "Client", sortable: true,
      render: (v) => {
        const u = users[v];
        return u ? (
          <>
            <div className="font-semibold text-[#0a2350]">{u.name}</div>
            <div className="text-xs text-slate-500">{u.email}</div>
          </>
        ) : <span className="text-xs font-mono text-slate-400">{v}</span>;
      } },
    { key: "next_renewal", label: "Renewal", sortable: true,
      render: (v) => <span className="text-slate-500">{shortDate(v)}</span> },
    { key: "price_monthly", label: "Monthly", sortable: true, align: "right",
      render: (v) => <span className="font-semibold">{money(v)}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusBadge status={v} /> },
  ];

  return (
    <div>
      <PageHeader title="Active Services" subtitle="Every provisioned instance across your clients. Klik baris untuk detail provisioning." />
      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["product_name", "name", "category", "status"]}
        rowKey={(r) => r.id}
        onRowClick={(r) => setActive(r)}
        empty={{ title: "No services yet", hint: "Provisioned services will appear here once orders are verified." }}
        testid="admin-services-table"
      />
      {active && <ServiceDetailModal serviceId={active.id} onClose={() => setActive(null)} />}
    </div>
  );
};

const CONFIG_LABELS = {
  control_panel: "Control Panel",
  hostname: "Hostname",
  ip: "IP Address",
  domain: "Domain",
  os: "OS",
  node: "Proxmox Node",
  vmid: "VMID",
  rack: "Rack",
  cpu: "vCPU",
  ram_gb: "RAM (GB)",
  disk_gb: "Disk (GB)",
};

const ServiceDetailModal = ({ serviceId, onClose }) => {
  const [d, setD] = useState(null);
  useEffect(() => {
    api.get(`/admin/services/${serviceId}/detail`).then((r) => setD(r.data)).catch(() => setD(false));
  }, [serviceId]);

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
        data-testid="admin-service-detail-modal"
      >
        <div className="p-6 bg-[#0a2350] text-white flex items-start justify-between">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{d?.category || "service"}</div>
            <div className="text-xl font-extrabold">{d?.product_name || "Loading..."}</div>
            <div className="text-sm text-white/70 mt-0.5">{d?.name}</div>
          </div>
          <button className="text-white/70 hover:text-white text-2xl leading-none" onClick={onClose} data-testid="service-detail-close">×</button>
        </div>
        {d && (
          <div className="p-6 overflow-y-auto space-y-4">
            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                <div className="text-[10px] font-bold uppercase text-slate-500">Status</div>
                <div className="mt-1"><StatusBadge status={d.status} /></div>
              </div>
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                <div className="text-[10px] font-bold uppercase text-slate-500">Renewal</div>
                <div className="mt-1 text-sm font-semibold">{shortDate(d.next_renewal)}</div>
              </div>
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
                <div className="text-[10px] font-bold uppercase text-slate-500">Monthly</div>
                <div className="mt-1 text-sm font-extrabold text-[#0a2350]">{money(d.price_monthly)}</div>
              </div>
            </div>

            <Card className="p-4">
              <div className="text-sm font-extrabold text-[#0a2350] mb-1">Client</div>
              <div className="text-sm font-semibold text-[#0a2350]">{d.user?.name}</div>
              <div className="text-xs text-slate-500">{d.user?.email}{d.user?.company ? ` - ${d.user.company}` : ""}</div>
            </Card>

            <Card className="p-4">
              <div className="text-sm font-extrabold text-[#0a2350] mb-2">Provisioning config</div>
              {Object.keys(d.config || {}).length === 0 ? (
                <p className="text-xs text-slate-500">Belum ada konfigurasi.</p>
              ) : (
                <div className="divide-y divide-slate-100">
                  {Object.entries(d.config).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between py-1.5 text-sm">
                      <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{CONFIG_LABELS[k] || k}</span>
                      <span className="font-mono text-[#0a2350]">{String(v ?? "-")}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <TrafficSourceCard serviceId={serviceId} config={d.config || {}} />

            {d.pending_upgrade && (
              <Card className="p-4 border-amber-200 bg-amber-50/50">
                <div className="text-sm font-extrabold text-amber-800 mb-1">Upgrade menunggu pembayaran</div>
                <p className="text-xs text-amber-700">
                  +{d.pending_upgrade.cpu || 0} vCPU, +{d.pending_upgrade.ram_gb || 0} GB RAM, +{d.pending_upgrade.disk_gb || 0} GB Disk
                  {" - "}{money(d.pending_upgrade.monthly_delta || 0)}/bln
                </p>
              </Card>
            )}

            <Card className="p-4">
              <div className="text-sm font-extrabold text-[#0a2350] mb-2">Provisioning log</div>
              {(d.provision_log || []).length === 0 ? (
                <p className="text-xs text-slate-500">Tidak ada log provisioning (service dibuat manual).</p>
              ) : (
                <ol className="space-y-2">
                  {d.provision_log.map((l, i) => (
                    <li key={i} className="flex gap-2.5 text-xs">
                      <span className="mt-1 h-1.5 w-1.5 rounded-full bg-[#f5b120] shrink-0" />
                      <span>
                        <span className="font-bold text-[#0a2350]">{l.step}</span>
                        <span className="text-slate-600"> - {l.message}</span>
                        <span className="block text-[10px] text-slate-400">{l.at}</span>
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </Card>

            {(d.self_service_log || []).length > 0 && (
              <Card className="p-4">
                <div className="text-sm font-extrabold text-[#0a2350] mb-2">Aktivitas self-service klien</div>
                <ol className="space-y-1.5">
                  {d.self_service_log.map((l, i) => (
                    <li key={i} className="text-xs text-slate-600">
                      <span className="font-bold text-[#0a2350]">{l.action}</span> oleh {l.by}
                      <span className="text-[10px] text-slate-400 ml-1">{l.at}</span>
                    </li>
                  ))}
                </ol>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const TrafficSourceCard = ({ serviceId, config }) => {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState(config.traffic_device_id || "");
  const [ifaces, setIfaces] = useState([]);
  const [iface, setIface] = useState(config.traffic_interface || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const mapped = Boolean(config.traffic_device_id && config.traffic_interface);

  useEffect(() => {
    api.get("/admin/mikrotik/devices").then((r) => setDevices(r.data || [])).catch(() => setDevices([]));
  }, []);

  useEffect(() => {
    if (!deviceId) { setIfaces([]); return; }
    const q = deviceId === "legacy" ? "" : `?device_id=${deviceId}`;
    api.get(`/admin/mikrotik/interfaces${q}`)
      .then((r) => setIfaces(Array.isArray(r.data) ? r.data : []))
      .catch(() => setIfaces([]));
  }, [deviceId]);

  const save = async (clear = false) => {
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.put(`/admin/services/${serviceId}/traffic-source`,
        clear ? {} : { device_id: deviceId, interface: iface });
      if (clear) {
        setDeviceId(""); setIface("");
        setMsg({ ok: true, text: "Sumber trafik dihapus." });
      } else {
        setMsg({ ok: true, text: data.sample
          ? `Tersimpan. Sampel live pertama: ${data.sample.in_mbps} Mbps in / ${data.sample.out_mbps} Mbps out.`
          : "Tersimpan. Sampel pertama akan diambil pada sweep per jam berikutnya." });
      }
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Gagal menyimpan sumber trafik" });
    } finally { setBusy(false); }
  };

  return (
    <Card className="p-4" data-testid="traffic-source-card">
      <div className="text-sm font-extrabold text-[#0a2350]">Traffic source (live)</div>
      <p className="text-xs text-slate-500 mt-0.5 mb-3">
        Petakan layanan ini ke interface MikroTik. Kolektor per jam menyimpan sampel live untuk Traffic Report klien.
        {mapped && <span className="text-emerald-700 font-semibold"> Terhubung: {config.traffic_interface}</span>}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <select value={deviceId} onChange={(e) => { setDeviceId(e.target.value); setIface(""); }}
                className="h-9 rounded-lg border border-slate-300 px-2 text-sm" data-testid="traffic-source-device">
          <option value="">- Pilih router -</option>
          {devices.map((dv) => (
            <option key={dv.id || "legacy"} value={dv.id || "legacy"}>{dv.name} ({dv.host})</option>
          ))}
        </select>
        <select value={iface} onChange={(e) => setIface(e.target.value)} disabled={!deviceId}
                className="h-9 rounded-lg border border-slate-300 px-2 text-sm disabled:bg-slate-50" data-testid="traffic-source-interface">
          <option value="">- Pilih interface -</option>
          {ifaces.map((i) => (
            <option key={i.name} value={i.name}>{i.name}</option>
          ))}
        </select>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button onClick={() => save(false)} disabled={busy || !deviceId || !iface}
                className="px-3 py-1.5 rounded-lg bg-[#0a2350] text-white text-xs font-bold disabled:opacity-40"
                data-testid="traffic-source-save">
          {busy ? "Menyimpan…" : "Simpan sumber trafik"}
        </button>
        {mapped && (
          <button onClick={() => save(true)} disabled={busy}
                  className="px-3 py-1.5 rounded-lg border border-red-200 text-red-600 text-xs font-bold"
                  data-testid="traffic-source-clear">
            Hapus mapping
          </button>
        )}
      </div>
      {msg && (
        <div className={`mt-2 text-xs rounded-lg px-2.5 py-1.5 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`}
             data-testid="traffic-source-msg">
          {msg.text}
        </div>
      )}
    </Card>
  );
};

export default AdminServices;
