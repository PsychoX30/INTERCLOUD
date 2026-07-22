import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../../portal/api";
import {
  PageHeader, Card, Loading, btnPrimary, btnSecondary, inputClass, labelClass,
} from "../ui";
import {
  Save, Zap, CheckCircle2, XCircle, Loader2, ChevronDown, ChevronUp,
  Server, Router, CreditCard, Mail, Inbox, HardDrive, Globe, ShieldCheck,
} from "lucide-react";

/* Unified Integrations page — replaces the old split "Integrations" + "Real APIs".
   Drives the /admin/integrations-v2 schema (single source of truth). Adds IMAP
   for inbound mail alongside SMTP for outbound. */

const PROVIDER_ICON = {
  proxmox: Server, mikrotik: Router,
  midtrans: CreditCard, xendit: CreditCard, duitku: CreditCard,
  smtp: Mail, imap: Inbox,
  cpanel: Globe, plesk: HardDrive,
  recaptcha: ShieldCheck,
};

const CATEGORY_ORDER = ["virtualization", "network", "provisioning", "payment", "mail", "security"];
const CATEGORY_LABEL = {
  virtualization: "Virtualization & Compute",
  network: "Network",
  provisioning: "Hosting Provisioning",
  payment: "Payment Gateways",
  mail: "Email (SMTP & IMAP)",
  security: "Security & Anti-bot",
};

const AdminIntegrations = () => {
  const [schema, setSchema] = useState(null);
  const [values, setValues] = useState(null);
  const [legacy, setLegacy] = useState([]);

  const load = () => Promise.all([
    api.get("/admin/integrations-v2/schema"),
    api.get("/admin/integrations-v2"),
    api.get("/admin/integrations").catch(() => ({ data: [] })),
  ]).then(([s, v, l]) => { setSchema(s.data); setValues(v.data); setLegacy(l.data || []); });

  useEffect(() => { load(); }, []);

  const grouped = useMemo(() => {
    if (!schema) return {};
    const g = {};
    Object.entries(schema).forEach(([provider, spec]) => {
      const cat = spec.category || "other";
      (g[cat] = g[cat] || []).push([provider, spec]);
    });
    return g;
  }, [schema]);

  if (!schema || !values) return <Loading />;

  const enabledCount = Object.values(values).filter((v) => v?.enabled).length;
  const totalCount = Object.keys(schema).length;

  return (
    <div>
      <PageHeader
        title="Integrations"
        subtitle="Every third-party credential in one place — virtualization (Proxmox), network (MikroTik), hosting provisioning (cPanel / Plesk), payment gateways, and email (SMTP outbound + IMAP inbound). Paste credentials, hit Test, then Save."
      />

      <div className="mb-5 grid sm:grid-cols-3 gap-3">
        <MiniStat label="Providers configured" value={`${enabledCount} / ${totalCount}`} tone={enabledCount > 0 ? "good" : "warn"} />
        <MiniStat label="Categories" value={CATEGORY_ORDER.length} />
        <MiniStat label="Legacy modules" value={legacy.length} hint={legacy.length ? "Migrate below" : "None left"} />
      </div>

      {legacy.length > 0 && (
        <Card className="mb-5 p-4 border-amber-200 bg-amber-50">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-amber-100 text-amber-800"><Zap className="h-4 w-4" /></div>
            <div className="flex-1">
              <div className="font-bold text-amber-900">Legacy integrations detected</div>
              <p className="text-xs text-amber-800 mt-1 leading-relaxed">
                {legacy.length} entr{legacy.length === 1 ? "y" : "ies"} still live in the old <code>integrations</code> collection.
                Re-enter the credentials on the matching provider card below and delete the legacy row.
                (Existing auto-provisioning continues to work either way.)
              </p>
              <ul className="mt-2 text-[11px] text-amber-800 flex flex-wrap gap-1.5">
                {legacy.map((l) => (
                  <li key={l.id} className="px-2 py-0.5 rounded-full bg-white border border-amber-200">
                    <b>{l.module_label || l.module}</b> · {l.status}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      )}

      <div className="space-y-6">
        {CATEGORY_ORDER.filter((c) => grouped[c]).map((cat) => (
          <div key={cat}>
            <div className="text-[10px] uppercase tracking-widest font-bold text-slate-500 mb-2">{CATEGORY_LABEL[cat] || cat}</div>
            <div className="space-y-3">
              {grouped[cat].map(([provider, spec]) => (
                <IntegrationCard
                  key={provider}
                  provider={provider}
                  spec={spec}
                  initial={values[provider] || { enabled: false, credentials: {}, options: {} }}
                  onSaved={load}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const MiniStat = ({ label, value, hint, tone = "default" }) => {
  const toneClass = tone === "good" ? "text-emerald-600" : tone === "warn" ? "text-amber-700" : "text-[#0a2350]";
  return (
    <Card className="p-4">
      <div className="text-[10px] uppercase tracking-widest font-bold text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-extrabold ${toneClass}`}>{value}</div>
      {hint && <div className="text-xs text-slate-500 mt-0.5">{hint}</div>}
    </Card>
  );
};

const IntegrationCard = ({ provider, spec, initial, onSaved }) => {
  const Icon = PROVIDER_ICON[provider] || Zap;
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(!!initial.enabled);
  const [creds, setCreds] = useState(initial.credentials || {});
  const [opts, setOpts] = useState(initial.options || {});
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const setCred = (k, v) => setCreds({ ...creds, [k]: v });
  const setOpt = (k, v) => setOpts({ ...opts, [k]: v });

  const save = async () => {
    setBusy(true); setTestResult(null);
    try {
      const cleaned = {};
      Object.entries(creds).forEach(([k, v]) => { if (!k.endsWith("_masked")) cleaned[k] = v; });
      await api.put(`/admin/integrations-v2/${provider}`, { enabled, credentials: cleaned, options: opts });
      setTestResult({ ok: true, message: "Saved." });
      onSaved();
    } catch (e) {
      setTestResult({ ok: false, message: e?.response?.data?.detail || "Save failed" });
    } finally { setBusy(false); }
  };

  const test = async () => {
    setBusy(true); setTestResult(null);
    try {
      const { data } = await api.post(`/admin/integrations-v2/${provider}/test`);
      setTestResult(data);
    } catch (e) {
      setTestResult({ ok: false, message: e?.response?.data?.detail || "Test failed" });
    } finally { setBusy(false); }
  };

  return (
    <Card className="p-0 overflow-hidden" data-testid={`integration-${provider}`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-4 hover:bg-slate-50 text-left"
        data-testid={`toggle-${provider}`}
      >
        <div className="h-10 w-10 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
          <Icon className="h-5 w-5 text-[#0a2350]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-extrabold text-[#0a2350]">{spec.label}</div>
          {spec.description && <div className="text-xs text-slate-500 truncate">{spec.description}</div>}
        </div>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-widest ${enabled ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
          {enabled ? "Enabled" : "Disabled"}
        </span>
        {open ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
      </button>

      {open && (
        <div className="border-t border-slate-200 p-5 space-y-4 bg-slate-50/60">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} data-testid={`${provider}-enabled`} />
            <span className="text-slate-700 font-semibold">Enable this integration</span>
          </label>

          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-2">Credentials</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {spec.credentials.map((f) => (
                <FieldInput key={f.key} field={f} value={creds[f.key]} masked={creds[f.key + "_masked"]} onChange={(v) => setCred(f.key, v)} testid={`${provider}-${f.key}`} />
              ))}
            </div>
          </div>

          {spec.options.length > 0 && (
            <div>
              <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-2">Options</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {spec.options.map((f) => (
                  <FieldInput key={f.key} field={f} value={opts[f.key] ?? f.default} onChange={(v) => setOpt(f.key, v)} testid={`${provider}-opt-${f.key}`} />
                ))}
              </div>
            </div>
          )}

          {testResult && (
            <div className={`rounded-xl border px-3 py-2 text-sm ${testResult.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-800"}`} data-testid={`${provider}-test-result`}>
              {testResult.ok ? <CheckCircle2 className="h-4 w-4 inline mr-1" /> : <XCircle className="h-4 w-4 inline mr-1" />}
              {testResult.message}
            </div>
          )}

          <div className="flex gap-2">
            <button onClick={test} disabled={busy} className={btnSecondary} data-testid={`${provider}-test-btn`}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              Test connection
            </button>
            <button onClick={save} disabled={busy} className={btnPrimary} data-testid={`${provider}-save-btn`}>
              <Save className="h-4 w-4" /> Save
            </button>
          </div>
        </div>
      )}
    </Card>
  );
};

const FieldInput = ({ field, value, masked, onChange, testid }) => {
  if (field.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-sm py-2">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} data-testid={testid} />
        <span className="text-slate-700">{field.label}</span>
      </label>
    );
  }
  if (field.type === "select") {
    return (
      <label>
        <div className={labelClass}>{field.label}</div>
        <select value={value || ""} onChange={(e) => onChange(e.target.value)} className={inputClass} data-testid={testid}>
          {(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      </label>
    );
  }
  const placeholder = masked ? `saved: ${masked}` : (field.placeholder || field.label);
  return (
    <label>
      <div className={labelClass}>{field.label}{field.required && <span className="text-red-500 ml-0.5">*</span>}</div>
      <input
        type={field.type === "password" ? "password" : field.type === "number" ? "number" : "text"}
        value={value ?? ""}
        onChange={(e) => onChange(field.type === "number" ? Number(e.target.value) : e.target.value)}
        placeholder={placeholder}
        className={inputClass}
        data-testid={testid}
      />
    </label>
  );
};

export default AdminIntegrations;
