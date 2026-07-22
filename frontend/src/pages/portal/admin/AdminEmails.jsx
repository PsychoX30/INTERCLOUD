import React, { useEffect, useMemo, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import {
  PageHeader, Card, Loading, EmptyState,
  btnPrimary, btnSecondary, btnDanger, inputClass, labelClass,
} from "../ui";
import {
  Send, Mail, FilePlus2, Save, Trash2, Eye, PlayCircle, History, Clock,
  Loader2, X, Megaphone, Sparkles, ShieldAlert, CheckCircle2, XCircle, AlertTriangle,
} from "lucide-react";

const TRIGGER_LABEL = {
  instant: { label: "Instant", color: "bg-emerald-100 text-emerald-700" },
  scheduled: { label: "Scheduled", color: "bg-amber-100 text-amber-800" },
  on_demand: { label: "On demand", color: "bg-sky-100 text-sky-700" },
};

const STATUS_LABEL = {
  sent: { label: "Sent", color: "bg-emerald-100 text-emerald-700", icon: CheckCircle2 },
  failed: { label: "Failed", color: "bg-red-100 text-red-700", icon: XCircle },
  skipped: { label: "Skipped", color: "bg-slate-100 text-slate-600", icon: AlertTriangle },
  queued: { label: "Queued", color: "bg-sky-100 text-sky-700", icon: Clock },
};


const AdminEmails = () => {
  const [tab, setTab] = useState("templates"); // templates | logs | broadcast
  return (
    <div>
      <PageHeader
        title="Email Automation"
        subtitle="Instant transactional mail, scheduled invoice reminders, and on-demand blasts. Templates below drive every automatic email — edit subject, body, and send-time freely."
      />
      <div className="flex items-center gap-2 mb-4 border-b border-slate-200 overflow-x-auto">
        <TabBtn active={tab === "templates"} onClick={() => setTab("templates")} icon={Mail} testid="tab-templates">Templates</TabBtn>
        <TabBtn active={tab === "broadcast"} onClick={() => setTab("broadcast")} icon={Megaphone} testid="tab-broadcast">Broadcast</TabBtn>
        <TabBtn active={tab === "logs"} onClick={() => setTab("logs")} icon={History} testid="tab-logs">Delivery log</TabBtn>
      </div>
      {tab === "templates" && <TemplatesTab />}
      {tab === "broadcast" && <BroadcastTab />}
      {tab === "logs" && <LogsTab />}
    </div>
  );
};

const TabBtn = ({ active, onClick, icon: Icon, children, testid }) => (
  <button
    onClick={onClick}
    data-testid={testid}
    className={`px-4 h-11 -mb-px border-b-2 text-sm font-bold inline-flex items-center gap-2 whitespace-nowrap transition-colors ${
      active ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500 hover:text-[#0a2350]"
    }`}
  >
    <Icon className="h-4 w-4" /> {children}
  </button>
);

/* ---------- Templates ---------- */
const TemplatesTab = () => {
  const [rows, setRows] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [editing, setEditing] = useState(null);      // template row being edited (or 'new')
  const [preview, setPreview] = useState(null);       // {subject, body_html}
  const [saveMsg, setSaveMsg] = useState("");

  const load = async () => {
    const [t, c] = await Promise.all([
      api.get("/admin/email-templates"),
      api.get("/admin/email/event-catalog"),
    ]);
    setRows(t.data);
    setCatalog(c.data);
  };
  useEffect(() => { load(); }, []);

  const eventTrigger = (event_key) => {
    const ev = catalog?.events?.find((e) => e.key === event_key);
    return ev?.trigger || "on_demand";
  };

  const openPreview = async (tpl) => {
    const { data } = await api.post("/admin/email-templates/preview", {
      template_id: tpl.id,
    });
    setPreview({ subject: data.subject, body_html: data.body_html, name: tpl.name });
  };

  const openEditor = (tpl) => {
    setEditing(tpl || {
      event_key: "custom_event",
      name: "New template",
      subject: "",
      body_html: "",
      offset_days: null,
      send_time: "09:00",
      is_active: true,
      notes: "",
      is_system: false,
    });
  };

  const runSweep = async () => {
    setSaveMsg("");
    try {
      const { data } = await api.post("/admin/email/run-scheduler-now");
      const fired = data.fired || {};
      const total = Object.values(fired).reduce((a, b) => a + b, 0);
      setSaveMsg(`Sweep complete — ${total} emails dispatched, ${data.services_suspended || 0} services suspended.`);
    } catch (e) {
      setSaveMsg(e?.response?.data?.detail || "Sweep failed");
    }
  };

  if (!rows || !catalog) return <Loading />;

  return (
    <div className="space-y-4">
      {/* Event catalog hint */}
      <Card className="p-4 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[240px]">
          <div className="text-xs font-bold uppercase tracking-widest text-slate-500">Available variables</div>
          <div className="mt-1 text-[11px] text-slate-600 flex flex-wrap gap-1.5">
            {(catalog.variables || []).map((v) => (
              <code key={v} className="px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">{`{{${v}}}`}</code>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className={btnSecondary} onClick={runSweep} data-testid="run-sweep-btn">
            <PlayCircle className="h-4 w-4" /> Run scheduler now
          </button>
          <button className={btnPrimary} onClick={() => openEditor(null)} data-testid="new-template-btn">
            <FilePlus2 className="h-4 w-4" /> New template
          </button>
        </div>
      </Card>
      {saveMsg && (
        <div className="text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-4 py-2" data-testid="save-msg">
          {saveMsg}
        </div>
      )}

      {/* Templates table */}
      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm" data-testid="templates-table">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Event / Template</th>
              <th className="px-4 py-3 text-left">Trigger</th>
              <th className="px-4 py-3 text-left">Offset · Time</th>
              <th className="px-4 py-3 text-left">Active</th>
              <th className="px-4 py-3 text-right">Sent</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => {
              const trig = eventTrigger(t.event_key);
              const tone = TRIGGER_LABEL[trig] || TRIGGER_LABEL.on_demand;
              return (
                <tr key={t.id} className="border-t border-slate-100" data-testid={`tpl-row-${t.event_key}`}>
                  <td className="px-4 py-3">
                    <div className="font-bold text-[#0a2350]">{t.name}</div>
                    <div className="text-[11px] text-slate-500"><code>{t.event_key}</code>{t.is_system && <span className="ml-2 px-1.5 py-0.5 bg-slate-100 rounded text-[9px] font-bold uppercase tracking-widest text-slate-600">System</span>}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full font-bold uppercase tracking-wide text-[10px] ${tone.color}`}>{tone.label}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-600">
                    {t.offset_days !== null && t.offset_days !== undefined ? (
                      <span>{t.offset_days > 0 ? `+${t.offset_days}` : t.offset_days} day{Math.abs(t.offset_days) === 1 ? "" : "s"}</span>
                    ) : <span className="text-slate-400">–</span>}
                    {t.send_time ? <span className="ml-2 text-slate-500">@ {t.send_time}</span> : null}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full font-bold uppercase tracking-wide text-[10px] ${t.is_active ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-500"}`}>{t.is_active ? "Active" : "Paused"}</span>
                  </td>
                  <td className="px-4 py-3 text-right text-xs font-semibold text-slate-700">{t.send_count || 0}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="inline-flex gap-1.5">
                      <button className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-[#0a2350]" onClick={() => openPreview(t)} title="Preview" data-testid={`preview-${t.event_key}`}><Eye className="h-4 w-4" /></button>
                      <button className="p-1.5 rounded hover:bg-slate-100 text-slate-500 hover:text-[#0a2350]" onClick={() => openEditor(t)} title="Edit" data-testid={`edit-${t.event_key}`}><Sparkles className="h-4 w-4" /></button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-slate-500 text-sm">No templates yet</td></tr>}
          </tbody>
        </table>
      </div>

      {preview && <PreviewModal preview={preview} onClose={() => setPreview(null)} />}
      {editing && (
        <EditorModal
          template={editing}
          events={catalog.events}
          onClose={() => setEditing(null)}
          onSaved={async (msg) => { setEditing(null); setSaveMsg(msg); await load(); setTimeout(() => setSaveMsg(""), 4000); }}
        />
      )}
    </div>
  );
};

const PreviewModal = ({ preview, onClose }) => (
  <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-center justify-center p-4" onClick={onClose}>
    <div className="bg-white rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
      <div className="p-4 border-b border-slate-200 flex items-start justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">Preview · {preview.name}</div>
          <div className="text-lg font-extrabold text-[#0a2350] mt-0.5">{preview.subject}</div>
        </div>
        <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded"><X className="h-4 w-4" /></button>
      </div>
      <iframe title="Email preview" srcDoc={preview.body_html} className="flex-1 w-full bg-slate-50" data-testid="preview-iframe" />
    </div>
  </div>
);

const EditorModal = ({ template, events, onClose, onSaved }) => {
  const [form, setForm] = useState({ ...template });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [previewHtml, setPreviewHtml] = useState("");
  const [testEmail, setTestEmail] = useState("");
  const [testMsg, setTestMsg] = useState("");
  const isNew = !template.id;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const doPreview = async () => {
    setErr("");
    try {
      const { data } = await api.post("/admin/email-templates/preview", {
        subject: form.subject, body_html: form.body_html,
      });
      setPreviewHtml(data.body_html);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Preview failed");
    }
  };

  const save = async () => {
    setBusy(true); setErr("");
    try {
      const payload = {
        event_key: form.event_key,
        name: form.name,
        subject: form.subject,
        body_html: form.body_html,
        offset_days: form.offset_days === "" || form.offset_days === null ? null : Number(form.offset_days),
        send_time: form.send_time || null,
        is_active: !!form.is_active,
        notes: form.notes || "",
      };
      if (isNew) {
        await api.post("/admin/email-templates", payload);
      } else {
        await api.put(`/admin/email-templates/${template.id}`, payload);
      }
      onSaved(`Template “${form.name}” saved.`);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Save failed");
    } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm(`Delete template “${form.name}”? This cannot be undone.`)) return;
    setBusy(true); setErr("");
    try {
      await api.delete(`/admin/email-templates/${template.id}`);
      onSaved(`Template “${form.name}” deleted.`);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Delete failed");
    } finally { setBusy(false); }
  };

  const sendTest = async (e) => {
    e.preventDefault();
    if (!template.id) { setTestMsg("Save the template first."); return; }
    setTestMsg("");
    try {
      const { data } = await api.post("/admin/email-templates/send-test", {
        template_id: template.id, to_email: testEmail,
      });
      setTestMsg(data.ok ? `✓ Test email sent to ${testEmail}` :
        `⚠ ${data.status}: ${data.error || "SMTP not configured — logged instead"}`);
    } catch (er) {
      setTestMsg(er?.response?.data?.detail || "Send failed");
    }
  };

  const trig = events?.find((e) => e.key === form.event_key)?.trigger || "on_demand";

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/50 flex items-start md:items-center justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-5xl my-8 max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="p-4 border-b border-slate-200 flex items-start justify-between">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">{isNew ? "New template" : "Edit template"} · {trig}</div>
            <div className="text-lg font-extrabold text-[#0a2350] mt-0.5 truncate">{form.name || "Untitled"}</div>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-slate-100 rounded"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-6 overflow-y-auto flex-1 grid lg:grid-cols-2 gap-6">
          <div className="space-y-3">
            {err && <div className="text-sm rounded-xl bg-red-50 border border-red-200 text-red-700 px-3 py-2" data-testid="editor-err">{err}</div>}
            <label className="block">
              <div className={labelClass}>Template name</div>
              <input value={form.name} onChange={(e) => set("name", e.target.value)} className={inputClass} data-testid="editor-name" />
            </label>
            <label className="block">
              <div className={labelClass}>Event key {template.is_system && <span className="ml-1 text-slate-400 normal-case">(system — read only)</span>}</div>
              <input value={form.event_key} onChange={(e) => set("event_key", e.target.value)} disabled={!!template.is_system} className={`${inputClass} font-mono disabled:bg-slate-100`} data-testid="editor-event-key" />
            </label>
            <label className="block">
              <div className={labelClass}>Subject</div>
              <input value={form.subject} onChange={(e) => set("subject", e.target.value)} className={inputClass} data-testid="editor-subject" placeholder="Invoice {{invoice.number}} — {{invoice.total_fmt}}" />
            </label>
            <label className="block">
              <div className={labelClass}>Body (HTML — supports variables)</div>
              <textarea rows={14} value={form.body_html} onChange={(e) => set("body_html", e.target.value)} className={`${inputClass} h-auto py-2 font-mono text-[12px]`} data-testid="editor-body" />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <div className={labelClass}>Offset days
                  <span className="ml-1 text-slate-400 normal-case">(neg=before due, pos=after)</span>
                </div>
                <input type="number" value={form.offset_days ?? ""} onChange={(e) => set("offset_days", e.target.value === "" ? null : e.target.value)} className={inputClass} placeholder="e.g. -3, 0, 7" data-testid="editor-offset" />
              </label>
              <label className="block">
                <div className={labelClass}>Send time (HH:MM WIB)</div>
                <input value={form.send_time || ""} onChange={(e) => set("send_time", e.target.value)} className={inputClass} placeholder="09:00" data-testid="editor-time" />
              </label>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={!!form.is_active} onChange={(e) => set("is_active", e.target.checked)} data-testid="editor-active" />
              <span className="font-semibold text-slate-700">Active</span>
              <span className="text-slate-400 text-xs">Uncheck to pause without deleting.</span>
            </label>
            <label className="block">
              <div className={labelClass}>Internal notes</div>
              <textarea rows={2} value={form.notes || ""} onChange={(e) => set("notes", e.target.value)} className={`${inputClass} h-auto py-2`} data-testid="editor-notes" />
            </label>
          </div>
          <div className="space-y-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Live preview</div>
                <button className={btnSecondary} onClick={doPreview} data-testid="editor-preview-btn"><Eye className="h-3.5 w-3.5" /> Refresh</button>
              </div>
              <iframe title="Editor preview" srcDoc={previewHtml || "<div style='padding:32px;font-family:sans-serif;color:#64748b;font-size:13px'>Click <b>Refresh</b> to render the preview.</div>"} className="w-full bg-white rounded border border-slate-200 h-[380px]" data-testid="editor-preview-iframe" />
            </div>
            {!isNew && (
              <div className="rounded-xl border border-slate-200 bg-white p-3">
                <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-2">Send test email</div>
                <form onSubmit={sendTest} className="flex flex-wrap items-center gap-2">
                  <input type="email" required value={testEmail} onChange={(e) => setTestEmail(e.target.value)} className={`${inputClass} flex-1 min-w-[220px]`} placeholder="your@email.com" data-testid="editor-test-email" />
                  <button className={btnPrimary} type="submit" data-testid="editor-test-btn"><Send className="h-3.5 w-3.5" /> Send test</button>
                </form>
                {testMsg && <div className="mt-2 text-xs text-slate-700" data-testid="editor-test-msg">{testMsg}</div>}
              </div>
            )}
          </div>
        </div>
        <div className="p-4 border-t border-slate-200 flex flex-wrap gap-2 justify-end">
          {!isNew && !template.is_system && (
            <button className={btnDanger} onClick={remove} disabled={busy} data-testid="editor-delete-btn"><Trash2 className="h-4 w-4" /> Delete</button>
          )}
          <button className={btnSecondary} onClick={onClose} disabled={busy}>Cancel</button>
          <button className={btnPrimary} onClick={save} disabled={busy} data-testid="editor-save-btn">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save template
          </button>
        </div>
      </div>
    </div>
  );
};

/* ---------- Broadcast ---------- */
const BroadcastTab = () => {
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("<p>Halo <b>{{user.name}}</b>,</p><p>&nbsp;</p><p>Salam,<br>Tim Intercloud</p>");
  const [audience, setAudience] = useState("all_clients");
  const [toEmails, setToEmails] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setResult(null); setErr("");
    try {
      const payload = { subject, body_html: body, audience };
      if (audience === "custom") {
        payload.to_emails = toEmails.split(/[\s,;]+/).filter((x) => x && x.includes("@"));
      }
      const { data } = await api.post("/admin/email/broadcast", payload);
      setResult(data);
    } catch (er) {
      setErr(er?.response?.data?.detail || "Broadcast failed");
    } finally { setBusy(false); }
  };

  return (
    <Card className="p-6">
      <div className="grid lg:grid-cols-3 gap-6">
        <form onSubmit={submit} className="space-y-4 lg:col-span-2" data-testid="broadcast-form">
          <div>
            <div className={labelClass}>Audience</div>
            <div className="mt-1 flex flex-wrap gap-2 text-sm">
              {[
                ["all_clients", "All active clients"],
                ["all_users", "All active users (incl. staff)"],
                ["custom", "Custom list"],
              ].map(([v, label]) => (
                <label key={v} className={`px-3 h-10 inline-flex items-center gap-2 rounded-full border cursor-pointer ${audience === v ? "border-[#f5b120] bg-[#f5b120]/10 text-[#0a2350] font-bold" : "border-slate-200 text-slate-600"}`}>
                  <input type="radio" checked={audience === v} onChange={() => setAudience(v)} className="hidden" />
                  {label}
                </label>
              ))}
            </div>
          </div>
          {audience === "custom" && (
            <label className="block">
              <div className={labelClass}>Recipient emails (comma or newline separated)</div>
              <textarea rows={3} value={toEmails} onChange={(e) => setToEmails(e.target.value)} className={`${inputClass} h-auto py-2`} data-testid="broadcast-emails" />
            </label>
          )}
          <label className="block">
            <div className={labelClass}>Subject</div>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} className={inputClass} required placeholder="Intercloud maintenance — 15 Feb 2026" data-testid="broadcast-subject" />
          </label>
          <label className="block">
            <div className={labelClass}>Body HTML (variables supported)</div>
            <textarea rows={14} value={body} onChange={(e) => setBody(e.target.value)} className={`${inputClass} h-auto py-2 font-mono text-[12px]`} data-testid="broadcast-body" required />
          </label>
          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" disabled={busy || !subject || !body} className={btnPrimary} data-testid="broadcast-submit">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send broadcast
            </button>
            {err && <span className="text-sm text-red-700" data-testid="broadcast-err">{err}</span>}
          </div>
        </form>
        <div className="space-y-3">
          <Card className="p-4">
            <div className="flex items-center gap-2 text-[#0a2350] font-bold"><ShieldAlert className="h-4 w-4" /> Best practices</div>
            <ul className="mt-2 text-xs text-slate-600 space-y-1.5 leading-relaxed">
              <li>· Test-send a template first to yourself before broadcasting.</li>
              <li>· Use <code>{"{{user.name}}"}</code> so each recipient sees a personalised greeting.</li>
              <li>· Broadcasts silently skip inactive users and rows with empty emails.</li>
              <li>· When SMTP is disabled every send is <b>logged</b> but not delivered — check the Delivery log tab.</li>
            </ul>
          </Card>
          {result && (
            <Card className="p-4" data-testid="broadcast-result">
              <div className="text-[10px] uppercase tracking-widest font-bold text-[#f5b120]">Result</div>
              <div className="mt-2 text-sm space-y-1">
                <div><span className="text-slate-500">Recipients:</span> <b className="text-[#0a2350]">{result.recipients}</b></div>
                <div><span className="text-slate-500">Sent:</span> <b className="text-emerald-600">{result.sent}</b></div>
                <div><span className="text-slate-500">Failed:</span> <b className="text-red-600">{result.failed}</b></div>
                <div><span className="text-slate-500">Skipped:</span> <b className="text-slate-600">{result.skipped}</b></div>
              </div>
            </Card>
          )}
        </div>
      </div>
    </Card>
  );
};

/* ---------- Logs ---------- */
const LogsTab = () => {
  const [rows, setRows] = useState(null);
  const [filter, setFilter] = useState("all");
  const load = () => api.get("/admin/email-logs").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;
  const filtered = filter === "all" ? rows : rows.filter((r) => r.status === filter);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {["all", "sent", "failed", "skipped"].map((s) => (
          <button key={s} onClick={() => setFilter(s)} className={`px-3 h-8 rounded-full text-xs font-bold uppercase tracking-widest border ${filter === s ? "bg-[#0a2350] text-white border-[#0a2350]" : "text-slate-500 border-slate-200"}`} data-testid={`log-filter-${s}`}>{s}</button>
        ))}
        <div className="ml-auto text-xs text-slate-500">{filtered.length} entr{filtered.length === 1 ? "y" : "ies"}</div>
        <button className={btnSecondary} onClick={load}><History className="h-4 w-4" /> Refresh</button>
      </div>
      {filtered.length === 0 ? (
        <EmptyState title="No email logs yet" body="Trigger an event (register a user, place an order, or run the scheduler) to see entries here." />
      ) : (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm" data-testid="logs-table">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">When</th>
                <th className="px-4 py-3 text-left">Event</th>
                <th className="px-4 py-3 text-left">To</th>
                <th className="px-4 py-3 text-left">Subject</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Via</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const s = STATUS_LABEL[r.status] || STATUS_LABEL.skipped;
                const Icon = s.icon;
                return (
                  <tr key={r.id} className="border-t border-slate-100">
                    <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">{fullDateTime(r.created_at)}</td>
                    <td className="px-4 py-3"><code className="text-[11px] bg-slate-100 px-1.5 py-0.5 rounded">{r.event_key}</code></td>
                    <td className="px-4 py-3 font-mono text-xs">{r.to_email}</td>
                    <td className="px-4 py-3 text-slate-700 truncate max-w-[280px]">{r.subject}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-bold uppercase tracking-wide text-[10px] ${s.color}`}>
                        <Icon className="h-3 w-3" /> {s.label}
                      </span>
                      {r.error && <div className="text-[10px] text-red-600 mt-1 truncate max-w-[220px]" title={r.error}>{r.error}</div>}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500 uppercase tracking-widest">{r.delivered_via}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default AdminEmails;
