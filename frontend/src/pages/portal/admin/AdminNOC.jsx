import React, { useEffect, useState, useCallback } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary } from "../ui";
import { RefreshCw, PlayCircle, Loader2, CheckCircle2, XCircle, Wifi, WifiOff, Activity, AlertTriangle, ExternalLink, Ticket as TicketIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { NetflowSankey } from "./NetflowSankey";
import { DDoSPanel } from "./DDoSPanel";
import { ThresholdRules } from "./ThresholdRules";
import { DDoSHistory } from "./DDoSHistory";
import { NotifChannels } from "./NotifChannels";
import { BlackholeLog } from "./BlackholeLog";

const AdminNOC = () => {
  const [devices, setDevices] = useState([]);
  const [events, setEvents] = useState([]);
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);

  const load = useCallback(async () => {
    try {
      const [d, e, t] = await Promise.all([
        api.get("/admin/noc/devices"),
        api.get("/admin/noc/events?limit=100"),
        api.get("/admin/tickets").catch(() => ({ data: [] })),
      ]);
      setDevices(d.data || []);
      setEvents(e.data || []);
      setTickets((t.data || []).filter((tk) => tk.related_device_id));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Auto-refresh every 30 seconds so the operator sees new events without clicking
  useEffect(() => {
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const runNow = async () => {
    setPolling(true);
    try { await api.post("/admin/noc/run-poll"); await load(); }
    finally { setPolling(false); }
  };

  if (loading) return <Loading label="Loading NOC state…" />;

  const upCount = devices.filter((d) => d.status === "up").length;
  const downCount = devices.filter((d) => d.status === "down").length;
  const unknownCount = devices.filter((d) => d.status === "unknown").length;
  const avgUptime = devices.length
    ? (devices.reduce((a, d) => a + (d.uptime_24h_pct ?? 0), 0) / devices.length).toFixed(1)
    : "-";

  return (
    <div data-testid="noc-page">
      <PageHeader
        title="NOC Monitor"
        subtitle="Proactive MikroTik reachability monitoring. Probes run every 5 minutes on the background scheduler. Transitions (up ↔ down) fire email alerts to configured recipients."
        actions={
          <div className="flex items-center gap-2">
            <button className={btnSecondary} onClick={load} data-testid="noc-refresh"><RefreshCw className="h-4 w-4" /> Refresh</button>
            <button className={btnPrimary} onClick={runNow} disabled={polling} data-testid="noc-run-now">
              {polling ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
              {polling ? "Probing…" : "Run probe now"}
            </button>
          </div>
        }
      />

      {/* KPI grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <KPI label="Devices UP" value={upCount} total={devices.length} tone="good" testid="noc-kpi-up" Icon={Wifi} />
        <KPI label="Devices DOWN" value={downCount} total={devices.length} tone="danger" testid="noc-kpi-down" Icon={WifiOff} />
        <KPI label="Unknown" value={unknownCount} total={devices.length} tone="warn" testid="noc-kpi-unknown" Icon={AlertTriangle} />
        <KPI label="Fleet 24h uptime" value={typeof avgUptime === "string" ? avgUptime : `${avgUptime}%`} tone="default" testid="noc-kpi-avg" Icon={Activity} />
      </div>

      {devices.length === 0 && (
        <Card className="p-6">
          <EmptyState
            title="No MikroTik devices registered"
            body="Add a device from MikroTik Ops → Devices tab to begin monitoring. The 5-minute probe sweep starts as soon as at least one device is present."
          />
          <div className="text-center mt-4">
            <Link to="/portal/admin/mikrotik" className={btnPrimary} data-testid="noc-goto-mikrotik">
              <ExternalLink className="h-4 w-4" /> Go to MikroTik Ops
            </Link>
          </div>
        </Card>
      )}

      {devices.length > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
            {devices.map((d) => (
              <DeviceCard key={d.id} d={d}
                          tickets={tickets.filter((t) => t.related_device_id === d.id)} />
            ))}
          </div>

          <NetflowSankey />

          <DDoSPanel devices={devices} />

          <ThresholdRules />

          <DDoSHistory />

          <NotifChannels />

          <BlackholeLog />

          <Card className="overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
              <div className="text-xs font-bold uppercase tracking-widest text-slate-600">Recent Transition Events</div>
              <div className="text-xs text-slate-500 mt-0.5">Only real up→down / down→up transitions are recorded - no flap noise.</div>
            </div>
            {events.length === 0 ? (
              <div className="p-6"><EmptyState title="No transitions yet" body="Devices haven't changed state since monitoring started." /></div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="noc-events-table">
                  <thead className="bg-slate-50 text-[11px] uppercase tracking-widest text-slate-500">
                    <tr>
                      <th className="text-left px-4 py-3">When</th>
                      <th className="text-left px-4 py-3">Device</th>
                      <th className="text-left px-4 py-3">Type</th>
                      <th className="text-left px-4 py-3">Message</th>
                      <th className="text-left px-4 py-3">Alert Sent</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((ev) => {
                      const down = ev.type === "device_down";
                      return (
                        <tr key={ev.id} className="border-t border-slate-100" data-testid={`noc-event-${ev.id}`}>
                          <td className="px-4 py-3 whitespace-nowrap text-slate-700 text-xs font-mono">{ev.at}</td>
                          <td className="px-4 py-3">
                            <div className="font-semibold text-[#0a2350]">{ev.device_name || "unnamed"}</div>
                            <div className="text-xs text-slate-500 font-mono">{ev.device_host}</div>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-bold uppercase ${down ? "bg-red-100 text-red-700 border-red-300" : "bg-emerald-100 text-emerald-700 border-emerald-300"}`}>
                              {down ? <WifiOff className="h-3 w-3" /> : <Wifi className="h-3 w-3" />} {ev.type.replace("_", " ")}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 max-w-md truncate" title={ev.message}>{ev.message || "-"}</td>
                          <td className="px-4 py-3">
                            {ev.email_notified
                              ? <span className="inline-flex items-center gap-1 text-xs text-emerald-700"><CheckCircle2 className="h-3.5 w-3.5" /> sent</span>
                              : <span className="inline-flex items-center gap-1 text-xs text-slate-500"><XCircle className="h-3.5 w-3.5" /> no recipients</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="mt-4 rounded-xl bg-amber-50 border border-amber-200 p-4 text-sm">
            <div className="font-bold text-amber-900 mb-1">⚠️ Set up alert recipients</div>
            <div className="text-amber-800">
              Configure the email addresses that receive NOC alerts in
              {" "}<Link to="/portal/admin/finance" className="underline font-semibold" data-testid="noc-goto-finance">Finance → Billing Defaults</Link>{" "}
              (field: <code className="bg-white/60 px-1 rounded">NOC alert recipients</code>). If empty, alerts fall back to every user with role=admin.
            </div>
          </div>
        </>
      )}
    </div>
  );
};

const KPI = ({ label, value, total, tone = "default", testid, Icon }) => {
  const toneClass = {
    default: "border-slate-200",
    good:    "border-emerald-200 bg-emerald-50/60",
    warn:    "border-amber-200 bg-amber-50/60",
    danger:  "border-red-200 bg-red-50/60",
  }[tone];
  return (
    <div className={`rounded-2xl bg-white border p-4 ${toneClass}`} data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
        {Icon && <Icon className="h-4 w-4 text-slate-400" />}
      </div>
      <div className="text-2xl font-extrabold text-[#0a2350]">
        {value}{typeof total === "number" && <span className="text-sm font-normal text-slate-400"> / {total}</span>}
      </div>
    </div>
  );
};

const DeviceCard = ({ d, tickets = [] }) => {
  const status = d.status || "unknown";
  const styles = {
    up:      { dot: "bg-emerald-500", ring: "border-emerald-200", chip: "bg-emerald-100 text-emerald-700" },
    // motion-safe: users with prefers-reduced-motion get a static dot
    down:    { dot: "bg-red-500 motion-safe:animate-pulse", ring: "border-red-300", chip: "bg-red-100 text-red-700" },
    unknown: { dot: "bg-slate-400", ring: "border-slate-200", chip: "bg-slate-100 text-slate-600" },
  }[status];
  const openTickets = tickets.filter((t) => !["resolved", "closed"].includes(t.status));
  return (
    <div className={`rounded-2xl bg-white border-2 p-4 ${styles.ring}`} data-testid={`noc-device-${d.id}`}>
      <div className="flex items-start justify-between mb-2">
        <div>
          <div className="text-sm font-extrabold text-[#0a2350]">{d.name}</div>
          <div className="text-xs text-slate-500 font-mono">{d.host}</div>
        </div>
        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-widest ${styles.chip}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${styles.dot}`} /> {status}
        </span>
      </div>
      {d.site && <div className="text-xs text-slate-500 mb-2">📍 {d.site}</div>}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-slate-400">24h uptime</div>
          <div className="font-bold text-slate-800">{d.uptime_24h_pct == null ? "-" : `${d.uptime_24h_pct}%`}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-widest text-slate-400">30d uptime</div>
          <div className="font-bold text-slate-800" data-testid={`noc-device-30d-${d.id}`}>{d.uptime_30d_pct == null ? "-" : `${d.uptime_30d_pct}%`}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-widest text-slate-400">Samples</div>
          <div className="font-bold text-slate-800">{d.samples_24h || 0}</div>
        </div>
      </div>
      {tickets.length > 0 && (
        <div className="mt-2 pt-2 border-t border-slate-100" data-testid={`noc-device-tickets-${d.id}`}>
          <div className="text-[10px] uppercase tracking-widest text-slate-400 mb-1">
            Related tickets ({openTickets.length} open / {tickets.length} total)
          </div>
          <div className="space-y-0.5">
            {tickets.slice(0, 3).map((t) => (
              <Link key={t.id} to="/portal/admin/tickets"
                    className="block text-[11px] text-[#0a2350] hover:text-[#f5b120] truncate focus-visible:ring-2 focus-visible:ring-[#f5b120] rounded"
                    title={t.subject}>
                <TicketIcon className="h-3 w-3 inline mr-1 text-slate-400" />
                {t.number ? `${t.number} - ` : ""}{t.subject}
              </Link>
            ))}
          </div>
        </div>
      )}
      {d.last_probe_at && (
        <div className="mt-2 pt-2 border-t border-slate-100 text-[11px] text-slate-500 font-mono truncate" title={d.last_message}>
          Last probe: {d.last_probe_at.slice(11, 19)} UTC
        </div>
      )}
    </div>
  );
};

export default AdminNOC;
