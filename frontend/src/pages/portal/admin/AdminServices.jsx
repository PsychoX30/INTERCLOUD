import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, Card, StatusBadge } from "../ui";
import { DataTable } from "../../../components/ui/data-table";
import TablePager from "./TablePager";

const AdminServices = () => {
  const [rows, setRows] = useState(null);
  const [users, setUsers] = useState({});
  const [active, setActive] = useState(null);
  const [requests, setRequests] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [statusFilter, setStatusFilter] = useState("");
  const [q, setQ] = useState("");

  const params = useMemo(() => {
    const p = { paginate: true, limit, skip: page * limit };
    if (statusFilter) p.status = statusFilter;
    if (q) p.q = q;
    return p;
  }, [limit, page, statusFilter, q]);

  const loadRequests = () =>
    api.get("/admin/service-requests").then((r) => setRequests(r.data || [])).catch(() => setRequests([]));

  const loadServices = useCallback(() => {
    api.get("/admin/services", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => {
    loadServices();
  }, [loadServices]);

  useEffect(() => {
    api.get("/admin/users").then((r) => {
      const map = {};
      for (const u of r.data) map[u.id] = u;
      setUsers(map);
    }).catch(() => {});
    loadRequests();
  }, []);

  const refresh = () => {
    loadServices();
    loadRequests();
  };

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
      {requests.length > 0 && (
        <Card className="p-4 mb-4 border-red-200 bg-red-50/50" data-testid="termination-requests-banner">
          <div className="text-sm font-extrabold text-red-800 mb-2">
            Permintaan pengakhiran layanan menunggu persetujuan ({requests.length})
          </div>
          <div className="space-y-2">
            {requests.map((r) => (
              <div key={r.id} className="flex items-center justify-between gap-3 rounded-lg bg-white border border-red-100 px-3 py-2"
                   data-testid={`termreq-${r.id}`}>
                <div className="min-w-0">
                  <div className="text-sm font-bold text-[#0a2350] truncate">{r.product_name} · {r.name}</div>
                  <div className="text-[11px] text-slate-500 truncate">
                    {r.user?.email} · {r.termination_request?.reason || "tanpa alasan"}
                  </div>
                </div>
                <button
                  onClick={() => setActive(r)}
                  className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-xs font-bold whitespace-nowrap"
                  data-testid={`termreq-review-${r.id}`}>
                  Tinjau
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}
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

      {rows !== null && total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => {
            setLimit(l);
            setPage(0);
          }}
          testid="admin-services-pager"
        />
      )}
      {active && <ServiceDetailModal serviceId={active.id} onClose={() => { setActive(null); refresh(); }} />}
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
  const load = () => api.get(`/admin/services/${serviceId}/detail`).then((r) => setD(r.data)).catch(() => setD(false));
  useEffect(() => { load(); }, [serviceId]); // eslint-disable-line react-hooks/exhaustive-deps

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

            {d.category === "hosting" ? (
              <HostingLifecycleCard d={d} serviceId={serviceId} onChanged={load} />
            ) : (
              <ServiceLifecycleCard d={d} serviceId={serviceId} onChanged={load} />
            )}

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

            {["vps", "cloud", "dedicated"].includes(d.category) &&
              ((d.config || {}).provision_status !== "provisioned" || !(d.config || {}).vmid) && (
              <VerifyVmCard serviceId={serviceId} config={d.config || {}} onVerified={load} />
            )}

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

const ServiceLifecycleCard = ({ d, serviceId, onChanged }) => {
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const req = d.termination_request;
  const pendingTerm = req && req.status === "pending";

  const run = async (fn, label) => {
    setBusy(label); setMsg(null);
    try {
      const { data } = await fn();
      setMsg({ ok: true, text: data?.vm ? `${label} berhasil (${data.vm}).` : `${label} berhasil.` });
      onChanged && onChanged();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || `${label} gagal` });
    } finally { setBusy(""); }
  };

  return (
    <Card className="p-4" data-testid="service-lifecycle-card">
      <div className="text-sm font-extrabold text-[#0a2350] mb-2">Lifecycle layanan</div>

      {d.status === "terminated" ? (
        <p className="text-xs font-semibold text-red-700">Layanan sudah diterminasi.</p>
      ) : (
        <>
          {d.status === "suspended" ? (
            <div className="mb-3">
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-2">
                Disuspend{d.suspended_reason ? ` - ${d.suspended_reason}` : ""}.
              </p>
              <button
                data-testid="svc-unsuspend-btn"
                onClick={() => run(() => api.post(`/admin/services/${serviceId}/unsuspend`), "Unsuspend")}
                disabled={!!busy}
                className="px-3 py-2 rounded-lg bg-emerald-600 text-white text-xs font-bold disabled:opacity-50">
                {busy === "Unsuspend" ? "Memproses..." : "Aktifkan kembali (Unsuspend)"}
              </button>
            </div>
          ) : (
            <div className="mb-3 space-y-2">
              <input
                data-testid="svc-suspend-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Alasan suspend (mis. toleransi telat bayar)"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              />
              <button
                data-testid="svc-suspend-btn"
                onClick={() => run(() => api.post(`/admin/services/${serviceId}/suspend`, { reason }), "Suspend")}
                disabled={!!busy}
                className="px-3 py-2 rounded-lg bg-amber-600 text-white text-xs font-bold disabled:opacity-50">
                {busy === "Suspend" ? "Memproses..." : "Suspend layanan (manual)"}
              </button>
            </div>
          )}

          {pendingTerm && (
            <div className="rounded-xl border border-red-200 bg-red-50/60 p-3" data-testid="terminate-request-admin">
              <div className="text-xs font-extrabold text-red-800">Permintaan pengakhiran dari klien</div>
              <p className="text-[11px] text-red-700 mt-0.5">
                Diminta oleh {req.requested_by} · {req.requested_at}
                {req.reason ? ` · alasan: ${req.reason}` : ""}
              </p>
              <input
                data-testid="terminate-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Catatan (opsional)"
                className="w-full mt-2 rounded-lg border border-red-200 px-3 py-1.5 text-xs"
              />
              <div className="mt-2 flex items-center gap-2">
                <button
                  data-testid="terminate-approve-btn"
                  onClick={() => run(() => api.post(`/admin/services/${serviceId}/terminate-request/approve`, { note }), "Approve terminate")}
                  disabled={!!busy}
                  className="px-3 py-2 rounded-lg bg-red-600 text-white text-xs font-bold disabled:opacity-50">
                  Setujui &amp; akhiri
                </button>
                <button
                  data-testid="terminate-reject-btn"
                  onClick={() => run(() => api.post(`/admin/services/${serviceId}/terminate-request/reject`, { note }), "Reject terminate")}
                  disabled={!!busy}
                  className="px-3 py-2 rounded-lg border border-slate-300 text-slate-600 text-xs font-bold disabled:opacity-50">
                  Tolak
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {msg && (
        <div className={`mt-2 text-xs rounded-lg px-2.5 py-1.5 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`} data-testid="lifecycle-msg">
          {msg.text}
        </div>
      )}
    </Card>
  );
};

const HostingLifecycleCard = ({ d, serviceId, onChanged }) => {
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPackage, setNewPackage] = useState("");
  const cfg = d.config || {};
  const username = cfg.username || "-";
  const currentPackage = cfg.whm_package || cfg.package || "-";

  const run = async (fn, label) => {
    setBusy(label); setMsg(null);
    try {
      const { data } = await fn();
      setMsg({ ok: true, text: data?.message ? `${label} berhasil: ${data.message}` : `${label} berhasil.` });
      onChanged && onChanged();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || `${label} gagal` });
    } finally { setBusy(""); }
  };

  const isSuspended = d.status === "suspended";
  const isTerminated = d.status === "terminated";

  if (isTerminated) {
    return (
      <Card className="p-4" data-testid="hosting-lifecycle-card">
        <div className="text-sm font-extrabold text-[#0a2350] mb-2">Hosting lifecycle</div>
        <p className="text-xs font-semibold text-red-700">Layanan sudah diterminasi permanen.</p>
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
            <div className="text-[10px] font-bold uppercase text-slate-500">Username WHM</div>
            <div className="mt-1 font-mono text-[#0a2350]">{username}</div>
          </div>
          <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
            <div className="text-[10px] font-bold uppercase text-slate-500">Package WHM</div>
            <div className="mt-1 font-mono text-[#0a2350]">{currentPackage}</div>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-4" data-testid="hosting-lifecycle-card">
      <div className="text-sm font-extrabold text-[#0a2350] mb-2">Hosting lifecycle</div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-3">
        <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
          <div className="text-[10px] font-bold uppercase text-slate-500">Username WHM</div>
          <div className="mt-1 font-mono text-[#0a2350]">{username}</div>
        </div>
        <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
          <div className="text-[10px] font-bold uppercase text-slate-500">Package WHM</div>
          <div className="mt-1 font-mono text-[#0a2350]">{currentPackage}</div>
        </div>
        <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
          <div className="text-[10px] font-bold uppercase text-slate-500">Status</div>
          <div className="mt-1">
            <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold ${isSuspended ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800"}`}>
              {isSuspended ? "Suspended" : "Active"}
            </span>
          </div>
        </div>
      </div>

      {isSuspended ? (
        <div className="mb-3">
          {d.config?.suspend_reason && (
            <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-2">
              Disuspend: {d.config.suspend_reason}
            </p>
          )}
          <button
            data-testid="hosting-unsuspend-btn"
            onClick={() => run(() => api.post(`/admin/hosting/${serviceId}/unsuspend`), "Unsuspend")}
            disabled={!!busy}
            className="px-3 py-2 rounded-lg bg-emerald-600 text-white text-xs font-bold disabled:opacity-50"
          >
            {busy === "Unsuspend" ? "Memproses..." : "Aktifkan kembali (Unsuspend)"}
          </button>
        </div>
      ) : (
        <div className="mb-3 space-y-2">
          <input
            data-testid="hosting-suspend-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Alasan suspend (mis. toleransi telat bayar)"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          />
          <button
            data-testid="hosting-suspend-btn"
            onClick={() => run(() => api.post(`/admin/hosting/${serviceId}/suspend`, { reason }), "Suspend")}
            disabled={!!busy}
            className="px-3 py-2 rounded-lg bg-amber-600 text-white text-xs font-bold disabled:opacity-50"
          >
            {busy === "Suspend" ? "Memproses..." : "Suspend layanan"}
          </button>
        </div>
      )}

      <div className="mt-3 border-t border-slate-200 pt-3 space-y-3">
        <div>
          <div className="text-xs font-bold uppercase text-slate-500 mb-1">Ganti password cPanel</div>
          <div className="flex items-center gap-2">
            <input
              data-testid="hosting-password-input"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Password baru (min 8 karakter)"
              className="flex-1 h-9 rounded-lg border border-slate-300 px-3 text-sm"
            />
            <button
              data-testid="hosting-password-btn"
              onClick={() => run(() => api.post(`/admin/hosting/${serviceId}/password`, { new_password: newPassword }), "Ganti password")}
              disabled={!!busy || newPassword.length < 8}
              className="px-3 py-2 rounded-lg bg-[#0a2350] text-white text-xs font-bold disabled:opacity-50 whitespace-nowrap"
            >
              {busy === "Ganti password" ? "Memproses..." : "Ganti password"}
            </button>
          </div>
        </div>

        <div>
          <div className="text-xs font-bold uppercase text-slate-500 mb-1">Ganti package WHM</div>
          <div className="flex items-center gap-2">
            <input
              data-testid="hosting-package-input"
              value={newPackage}
              onChange={(e) => setNewPackage(e.target.value)}
              placeholder="Nama package WHM (mis. starter, business)"
              className="flex-1 h-9 rounded-lg border border-slate-300 px-3 text-sm"
            />
            <button
              data-testid="hosting-package-btn"
              onClick={() => run(() => api.post(`/admin/hosting/${serviceId}/package`, { package: newPackage }), "Ganti package")}
              disabled={!!busy || !newPackage.trim()}
              className="px-3 py-2 rounded-lg bg-[#f5b120] text-[#0a2350] text-xs font-bold disabled:opacity-50 whitespace-nowrap"
            >
              {busy === "Ganti package" ? "Memproses..." : "Ganti package"}
            </button>
          </div>
        </div>

        <div className="rounded-xl border-2 border-red-200 bg-red-50/40 p-3">
          <div className="text-xs font-extrabold text-red-800 mb-2">Terminasi permanen</div>
          <p className="text-[11px] text-red-700 mb-2">
            Aksi ini menghapus akun cPanel secara permanen via WHM <code>removeacct</code> dan tidak bisa dibatalkan.
          </p>
          <input
            data-testid="hosting-terminate-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Konfirmasi: ketik 'terminate' untuk melanjutkan"
            className="w-full rounded-lg border border-red-200 px-3 py-1.5 text-xs"
          />
          <button
            data-testid="hosting-terminate-btn"
            onClick={() => {
              if (note.trim().toLowerCase() !== "terminate") {
                setMsg({ ok: false, text: "Ketik 'terminate' untuk konfirmasi" });
                return;
              }
              run(() => api.post(`/admin/hosting/${serviceId}/terminate`, { confirm: true }), "Terminasi");
            }}
            disabled={!!busy}
            className="mt-2 px-3 py-2 rounded-lg bg-red-600 text-white text-xs font-bold disabled:opacity-50"
          >
            {busy === "Terminasi" ? "Memproses..." : "Terminasi permanen"}
          </button>
        </div>
      </div>

      {msg && (
        <div className={`mt-2 text-xs rounded-lg px-2.5 py-1.5 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`} data-testid="hosting-lifecycle-msg">
          {msg.text}
        </div>
      )}
    </Card>
  );
};

const VerifyVmCard = ({ serviceId, config, onVerified }) => {
  const [hostname, setHostname] = useState(config.hostname || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const verify = async () => {
    if (busy) return;
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.post(`/admin/services/${serviceId}/verify-vm`, { hostname });
      setMsg({ ok: true, text: data.message });
      onVerified && onVerified();
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Verifikasi gagal" });
    } finally { setBusy(false); }
  };
  return (
    <Card className="p-4 border-amber-200 bg-amber-50/40" data-testid="verify-vm-card">
      <div className="text-sm font-extrabold text-amber-900">Verifikasi deployment manual (by hostname)</div>
      <p className="text-xs text-amber-800 mt-0.5 mb-3">
        Provisioning otomatis belum selesai? Buat VM di Proxmox dengan nama persis hostname di bawah,
        lalu klik verifikasi - sistem mencari VM tersebut di cluster dan mengaktifkan service.
      </p>
      <div className="flex items-center gap-2">
        <input value={hostname} onChange={(e) => setHostname(e.target.value)}
               className="h-9 flex-1 rounded-lg border border-amber-300 px-2 text-sm font-mono bg-white"
               placeholder="vm-xxxxxx.icd-cust.net" data-testid="verify-vm-hostname" />
        <button onClick={verify} disabled={busy || !hostname.trim()}
                className="px-3 py-2 rounded-lg bg-amber-600 text-white text-xs font-bold disabled:opacity-40 whitespace-nowrap"
                data-testid="verify-vm-btn">
          {busy ? "Mencari VM…" : "Verifikasi VM"}
        </button>
      </div>
      {msg && (
        <div className={`mt-2 text-xs rounded-lg px-2.5 py-1.5 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`}
             data-testid="verify-vm-msg">
          {msg.text}
        </div>
      )}
    </Card>
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
