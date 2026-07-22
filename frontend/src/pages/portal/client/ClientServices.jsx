import React, { useEffect, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, Card, Loading, StatusBadge, EmptyState, btnSecondary } from "../ui";
import { ServerCog, Terminal, Cpu, Globe, ArrowRight, Copy } from "lucide-react";

const catIcon = { vps: Cpu, hosting: Globe, colocation: ServerCog, dedicated: Cpu, cloud: Cpu };

const ClientServices = () => {
  const [rows, setRows] = useState(null);
  const [active, setActive] = useState(null);

  useEffect(() => {
    api.get("/client/services").then((r) => setRows(r.data));
  }, []);

  if (!rows) return <Loading />;

  return (
    <div>
      <PageHeader
        title="My Services"
        subtitle="Active products & instances tied to your account. Click any service to see connection details and management shortcuts."
      />
      {rows.length === 0 && <EmptyState title="No services yet" body="Order a new service from the Order tab." />}
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {rows.map((s) => {
          const Icon = catIcon[s.category] || ServerCog;
          return (
            <button
              key={s.id}
              onClick={() => setActive(s)}
              data-testid={`service-${s.id}`}
              className="text-left rounded-2xl bg-white border border-slate-200 hover:border-[#f5b120] hover:shadow-lg transition-all p-5"
            >
              <div className="flex items-start justify-between">
                <div className="h-11 w-11 rounded-xl bg-[#0a2350] flex items-center justify-center">
                  <Icon className="h-5 w-5 text-[#f5b120]" strokeWidth={1.9} />
                </div>
                <StatusBadge status={s.status} />
              </div>
              <div className="mt-4 text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">
                {s.category}
              </div>
              <div className="text-lg font-extrabold text-[#0a2350] leading-tight">{s.product_name}</div>
              <div className="text-sm text-slate-500 mt-1">{s.name}</div>
              <div className="mt-4 border-t border-dashed border-slate-200 pt-3 flex items-center justify-between text-sm">
                <span className="text-slate-500">Next renewal</span>
                <span className="font-semibold">{shortDate(s.next_renewal)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between text-sm">
                <span className="text-slate-500">Monthly</span>
                <span className="font-extrabold text-[#0a2350]">{money(s.price_monthly)}</span>
              </div>
            </button>
          );
        })}
      </div>

      {active && <ServiceDetail service={active} onClose={() => setActive(null)} />}
    </div>
  );
};

const CopyRow = ({ label, value }) => {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
      <span className="text-xs uppercase tracking-widest text-slate-500 font-semibold">{label}</span>
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm text-[#0a2350]">{value || "-"}</span>
        {value && value !== "-" && (
          <button
            onClick={() => {
              navigator.clipboard.writeText(String(value));
              setCopied(true);
              setTimeout(() => setCopied(false), 1200);
            }}
            className="text-slate-400 hover:text-[#f5b120]"
          >
            <Copy className="h-3.5 w-3.5" />
          </button>
        )}
        {copied && <span className="text-[10px] text-emerald-600 font-bold">Copied</span>}
      </div>
    </div>
  );
};

const ServiceDetail = ({ service, onClose }) => {
  const s = service;
  const isVPS = s.category === "vps" || s.category === "dedicated" || s.category === "cloud";
  const isHosting = s.category === "hosting";
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col"
      >
        <div className="p-6 bg-[#0a2350] text-white flex items-start justify-between">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120]">{s.category}</div>
            <div className="text-xl font-extrabold">{s.product_name}</div>
            <div className="text-sm text-white/70 mt-0.5">{s.name}</div>
          </div>
          <button className="text-white/70 hover:text-white text-2xl leading-none" onClick={onClose}>×</button>
        </div>
        <div className="p-6 overflow-y-auto space-y-5">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <div className="text-[10px] font-bold uppercase text-slate-500">Status</div>
              <div className="mt-1"><StatusBadge status={s.status} /></div>
            </div>
            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <div className="text-[10px] font-bold uppercase text-slate-500">Start</div>
              <div className="mt-1 text-sm font-semibold">{shortDate(s.start_date)}</div>
            </div>
            <div className="rounded-xl bg-slate-50 border border-slate-200 p-3">
              <div className="text-[10px] font-bold uppercase text-slate-500">Renewal</div>
              <div className="mt-1 text-sm font-semibold">{shortDate(s.next_renewal)}</div>
            </div>
          </div>

          <Card className="p-5">
            <div className="text-sm font-extrabold text-[#0a2350] mb-2">Connection details</div>
            <CopyRow label="IP Address" value={s.config?.ip} />
            <CopyRow label="Hostname" value={s.config?.hostname} />
            {isVPS && <CopyRow label="OS" value={s.config?.os} />}
            {isVPS && <CopyRow label="Proxmox Node" value={s.config?.node} />}
            {isHosting && <CopyRow label="Control Panel" value={s.config?.control_panel} />}
            {s.category === "colocation" && <CopyRow label="Rack" value={s.config?.rack} />}
          </Card>

          {isVPS && (
            <Card className="p-5">
              <div className="text-sm font-extrabold text-[#0a2350] mb-3">VPS management</div>
              <div className="grid grid-cols-2 gap-2">
                <button className={btnSecondary}><Terminal className="h-4 w-4" /> noVNC Console</button>
                <button className={btnSecondary}>Reboot</button>
                <button className={btnSecondary}>Stop</button>
                <button className={btnSecondary}>Start</button>
                <button className={btnSecondary}>Rebuild OS</button>
                <button className={btnSecondary}>Snapshot</button>
              </div>
              <p className="mt-3 text-[11px] text-slate-500">Proxmox integration mocked — will go live once credentials are added under Integrations.</p>
            </Card>
          )}

          {isHosting && (
            <Card className="p-5">
              <div className="text-sm font-extrabold text-[#0a2350] mb-3">Hosting management</div>
              <div className="grid grid-cols-2 gap-2">
                <button className={btnSecondary}>Login to cPanel <ArrowRight className="h-3.5 w-3.5" /></button>
                <button className={btnSecondary}>File Manager</button>
                <button className={btnSecondary}>Databases</button>
                <button className={btnSecondary}>Email Accounts</button>
                <button className={btnSecondary}>Change Password</button>
                <button className={btnSecondary}>Restore Backup</button>
              </div>
              <p className="mt-3 text-[11px] text-slate-500">cPanel/Plesk integration mocked — will go live once credentials are added under Integrations.</p>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
};

export default ClientServices;
