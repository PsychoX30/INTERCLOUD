import React, { useEffect, useState } from "react";
import { Loader2, CheckCircle2, AlertTriangle, HelpCircle, ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";

const BASE = process.env.REACT_APP_BACKEND_URL;

const STATUS_STYLES = {
  operational: { color: "#059669", bg: "bg-emerald-50 border-emerald-200", text: "text-emerald-700", label: "Operational", Icon: CheckCircle2 },
  degraded:    { color: "#dc2626", bg: "bg-red-50 border-red-200",         text: "text-red-700",     label: "Degraded",    Icon: AlertTriangle },
  unknown:     { color: "#94a3b8", bg: "bg-slate-50 border-slate-200",     text: "text-slate-600",   label: "No data",     Icon: HelpCircle },
};

const PublicStatusPage = () => {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = async () => {
    try {
      const r = await fetch(`${BASE.replace(/\/$/, "")}/api/portal/public/status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setD(await r.json());
    } catch (e) { setErr(e.message || "Failed to load status"); }
  };
  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, []);

  if (err) return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6" data-testid="public-status-error">
      <div className="bg-white border border-red-200 rounded-2xl p-8 max-w-md text-center">
        <AlertTriangle className="h-8 w-8 text-red-600 mx-auto mb-3" />
        <div className="text-lg font-bold text-[#0a2540] mb-1">Status page temporarily unavailable</div>
        <div className="text-sm text-slate-600">{err}</div>
      </div>
    </div>
  );
  if (!d) return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center" data-testid="public-status-loading">
      <Loader2 className="h-8 w-8 text-[#0a2540] animate-spin" />
    </div>
  );

  const overall = STATUS_STYLES[d.overall_status] || STATUS_STYLES.unknown;
  const OverallIcon = overall.Icon;

  return (
    <div className="min-h-screen bg-slate-50" data-testid="public-status-page">
      <header className="bg-[#0a2540] text-white">
        <div className="max-w-4xl mx-auto px-4 py-8">
          <Link to="/" className="inline-flex items-center gap-2 text-white/70 hover:text-[#f5b120] text-sm mb-6" data-testid="status-back-home">
            <ArrowLeft className="h-4 w-4" /> Back to {d.company || "site"}
          </Link>
          <h1 className="text-3xl md:text-4xl font-extrabold" data-testid="status-header-title">System Status</h1>
          <p className="text-white/70 mt-1 text-sm">{d.company}</p>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-8">
        {/* Overall status banner */}
        <div className={`rounded-2xl border-2 p-6 mb-6 ${overall.bg}`} data-testid="status-overall">
          <div className="flex items-center gap-4">
            <OverallIcon className="h-10 w-10" style={{ color: overall.color }} />
            <div className="flex-1">
              <div className={`text-2xl font-extrabold ${overall.text}`}>
                {d.overall_status === "operational" ? "All systems operational" :
                 d.overall_status === "degraded" ? "Some systems degraded" :
                 "Status data unavailable"}
              </div>
              <div className="text-xs text-slate-500 mt-1">Updated {new Date(d.generated_at).toLocaleString()}</div>
            </div>
          </div>
        </div>

        {/* Active incident banner */}
        {d.incident_note && (
          <div className="rounded-2xl bg-amber-50 border-2 border-amber-300 p-5 mb-6" data-testid="status-incident-note">
            <div className="flex items-start gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-700 flex-shrink-0 mt-0.5" />
              <div>
                <div className="font-bold text-amber-900 mb-1">Active incident</div>
                <div className="text-sm text-amber-800 whitespace-pre-wrap">{d.incident_note}</div>
              </div>
            </div>
          </div>
        )}

        {/* Groups */}
        {d.groups.length === 0 ? (
          <div className="text-center py-12 text-slate-500 bg-white rounded-2xl border border-slate-200">
            No service groups configured yet.
          </div>
        ) : (
          <div className="space-y-3">
            {d.groups.map((g) => {
              const s = STATUS_STYLES[g.status] || STATUS_STYLES.unknown;
              const Icon = s.Icon;
              return (
                <div key={g.key} className="bg-white rounded-2xl border border-slate-200 p-5" data-testid={`status-group-${g.key}`}>
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="flex items-center gap-3">
                      <Icon className="h-5 w-5 flex-shrink-0" style={{ color: s.color }} />
                      <div className="font-bold text-[#0a2540]">{g.label}</div>
                    </div>
                    <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold ${s.bg} ${s.text}`}>
                      {s.label}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-4 text-xs pl-8 mt-3">
                    <div>
                      <div className="text-slate-500 uppercase tracking-widest text-[10px]">24h uptime</div>
                      <div className="font-bold text-[#0a2540] mt-0.5">
                        {g.uptime_24h_pct == null ? "-" : `${g.uptime_24h_pct}%`}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500 uppercase tracking-widest text-[10px]">30d uptime</div>
                      <div className="font-bold text-[#0a2540] mt-0.5">
                        {g.uptime_30d_pct == null ? "-" : `${g.uptime_30d_pct}%`}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="text-center text-xs text-slate-400 mt-8" data-testid="status-footer">
          Status refreshes every 60 seconds · Data aggregated from anonymised probe samples.
          <br />
          No internal device names, IP addresses, or topology are ever exposed on this page.
        </div>
      </main>
    </div>
  );
};

export default PublicStatusPage;
