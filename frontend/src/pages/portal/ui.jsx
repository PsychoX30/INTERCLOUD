import React from "react";
import { Loader2, AlertTriangle } from "lucide-react";
import { isBackendDown, onBackendState, SLOW_REQUEST_MS } from "../../portal/api";

export const PageHeader = ({ title, subtitle, actions }) => (
  <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-6">
    <div>
      <h1 className="text-2xl md:text-3xl font-extrabold text-[#0a2350] leading-tight">{title}</h1>
      {subtitle && <p className="text-sm text-slate-500 mt-1.5 max-w-2xl">{subtitle}</p>}
    </div>
    {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
  </div>
);

export const Card = ({ children, className = "", ...rest }) => (
  <div className={`bg-white border border-slate-200 rounded-2xl ${className}`} {...rest}>
    {children}
  </div>
);

export const StatCard = ({ label, value, hint, tone = "default", testid }) => {
  const toneClass = {
    default: "border-slate-200",
    warn: "border-amber-200 bg-amber-50/60",
    danger: "border-red-200 bg-red-50/60",
    good: "border-emerald-200 bg-emerald-50/60",
  }[tone];
  return (
    <div className={`rounded-2xl bg-white border p-5 ${toneClass}`} data-testid={testid}>
      <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-extrabold text-[#0a2350]">{value}</div>
      {hint && <div className="mt-1 text-[11px] text-slate-500">{hint}</div>}
    </div>
  );
};

export const StatusBadge = ({ status }) => {
  const map = {
    active: "bg-emerald-100 text-emerald-700 border-emerald-200",
    pending: "bg-amber-100 text-amber-800 border-amber-200",
    provisioning: "bg-blue-100 text-blue-700 border-blue-200",
    assigned: "bg-indigo-100 text-indigo-700 border-indigo-200",
    suspended: "bg-slate-200 text-slate-700 border-slate-300",
    terminated: "bg-slate-200 text-slate-500 border-slate-300",
    unpaid: "bg-amber-100 text-amber-800 border-amber-200",
    paid: "bg-emerald-100 text-emerald-700 border-emerald-200",
    overdue: "bg-red-100 text-red-700 border-red-200",
    cancelled: "bg-slate-200 text-slate-600 border-slate-300",
    open: "bg-blue-100 text-blue-700 border-blue-200",
    awaiting_client: "bg-amber-100 text-amber-800 border-amber-200",
    awaiting_staff: "bg-indigo-100 text-indigo-700 border-indigo-200",
    resolved: "bg-emerald-100 text-emerald-700 border-emerald-200",
    maintenance: "bg-violet-100 text-violet-700 border-violet-200",
    postmortem: "bg-slate-100 text-slate-600 border-slate-300",
    closed: "bg-slate-200 text-slate-600 border-slate-300",
    draft: "bg-slate-200 text-slate-700 border-slate-300",
    sent: "bg-blue-100 text-blue-700 border-blue-200",
    accepted: "bg-emerald-100 text-emerald-700 border-emerald-200",
    rejected: "bg-red-100 text-red-700 border-red-200",
    expired: "bg-slate-200 text-slate-600 border-slate-300",
    enabled: "bg-emerald-100 text-emerald-700 border-emerald-200",
    disabled: "bg-slate-200 text-slate-600 border-slate-300",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-bold uppercase tracking-wide ${
        map[status] || "bg-slate-200 text-slate-700 border-slate-300"
      }`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {String(status).replace(/_/g, " ")}
    </span>
  );
};

export const ErrorState = ({
  title = "Gagal memuat data",
  body,
  onRetry,
  testid = "error-state",
}) => (
  <div
    className="text-center py-12 px-4 rounded-2xl border border-red-200 bg-red-50/50"
    data-testid={testid}
  >
    <AlertTriangle className="h-6 w-6 text-red-600 mx-auto" />
    <div className="mt-2 text-lg font-extrabold text-[#0a2350]">{title}</div>
    {body && <p className="mt-2 text-sm text-slate-600 max-w-lg mx-auto">{body}</p>}
    {onRetry && (
      <button type="button" onClick={onRetry} className={`${btnSecondary} mt-4`}>
        Coba lagi
      </button>
    )}
  </div>
);

// THE CHOKE POINT FOR "INFINITE LOADING".
//
// A page that is waiting renders this, so this is the only place a hang has to
// be handled. Measured 2026-11-25: the backend worker was OOM-killed, the page's
// request rejected, the handler had no error branch, `rows` stayed null and this
// component rendered forever. Fixing the 29 pages that do that is 29 chances to
// miss one; fixing the component they all share is one place that cannot be
// missed, and it also covers a page that hangs on a request nobody .catch()ed.
//
// Two triggers, because they are different faults:
//   - the API is answering with gateway errors  -> say so at once, it is certain
//   - the request is merely taking too long     -> say so after 15 s, it is not
export const Loading = ({ label = "Loading…" }) => {
  const [elapsedMs, setElapsedMs] = React.useState(0);
  const [down, setDown] = React.useState(isBackendDown);

  React.useEffect(() => {
    const started = Date.now();
    const t = setInterval(() => setElapsedMs(Date.now() - started), 500);
    const off = onBackendState(setDown);
    return () => {
      clearInterval(t);
      off();
    };
  }, []);

  if (down || elapsedMs >= SLOW_REQUEST_MS) {
    return (
      <div
        className="text-center py-12 px-4 rounded-2xl border border-amber-200 bg-amber-50/60"
        data-testid="loading-stalled"
      >
        <AlertTriangle className="h-6 w-6 text-amber-600 mx-auto" />
        <div className="mt-2 text-lg font-extrabold text-[#0a2350]">
          {down ? "Server sedang tidak merespons" : "Pemuatan lebih lama dari biasanya"}
        </div>
        <p className="mt-2 text-sm text-slate-600 max-w-lg mx-auto">
          {down
            ? "API mengembalikan error gateway atau tidak dapat dihubungi, jadi halaman ini tidak bisa menyelesaikan permintaannya."
            : `Halaman ini masih menunggu data lebih dari ${Math.round(
                SLOW_REQUEST_MS / 1000
              )} detik. Koneksi mungkin terputus di tengah jalan.`}
        </p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => window.location.reload()}
            className={btnPrimary}
            data-testid="loading-reload"
          >
            Muat ulang
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 py-10 justify-center">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
};

export const EmptyState = ({ title = "Nothing here yet", body }) => (
  <div className="text-center py-12">
    <div className="text-lg font-extrabold text-[#0a2350]">{title}</div>
    {body && <p className="mt-2 text-sm text-slate-500">{body}</p>}
  </div>
);

export const btnPrimary =
  "inline-flex items-center gap-2 rounded-lg bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white text-sm font-semibold px-4 h-10 transition-colors";
export const btnSecondary =
  "inline-flex items-center gap-2 rounded-lg bg-white border border-slate-300 hover:border-[#f5b120] hover:text-[#0a2350] text-slate-700 text-sm font-semibold px-4 h-10 transition-colors";
export const btnDanger =
  "inline-flex items-center gap-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold px-4 h-10 transition-colors";
export const inputClass =
  "w-full h-10 rounded-lg border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]";
export const labelClass = "text-xs font-bold uppercase tracking-widest text-slate-600";

export const ComingSoon = ({ title, description, features = [] }) => (
  <div>
    <PageHeader title={title} subtitle={description} />
    <div className="rounded-3xl bg-white border border-dashed border-slate-300 p-8 md:p-10 text-center">
      <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#f5b120]/20 text-[#0a2350] text-[10px] font-bold uppercase tracking-widest">
        Coming Soon
      </div>
      <h3 className="mt-4 text-xl font-extrabold text-[#0a2350]">Module ready - awaiting real credentials</h3>
      <p className="mt-2 text-sm text-slate-500 max-w-lg mx-auto">
        Modul ini siap dipakai. Tambahkan kredensial di <span className="font-semibold">Integrations</span> dan modul akan langsung aktif dengan data real.
      </p>
      {features.length > 0 && (
        <ul className="mt-6 grid sm:grid-cols-2 gap-2 text-left max-w-lg mx-auto">
          {features.map((f) => (
            <li key={f} className="text-sm text-slate-600 flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[#f5b120]" /> {f}
            </li>
          ))}
        </ul>
      )}
    </div>
  </div>
);
