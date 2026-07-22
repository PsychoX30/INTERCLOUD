import React, { useEffect, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Inbox, Send, Star, Mail, Loader2, AlertTriangle, Reply, CheckCircle2 } from "lucide-react";

const AdminMail = () => {
  const [tab, setTab] = useState("inbox"); // inbox | sent | compose
  return (
    <div>
      <PageHeader
        title="Webmail"
        subtitle="Send invoices, order confirmations, and campaigns from your team inbox. Uses the SMTP + IMAP integration you configure under Integrations."
      />
      <div className="flex items-center gap-2 mb-4 border-b border-slate-200">
        <TabBtn active={tab === "inbox"} onClick={() => setTab("inbox")} icon={Inbox}>Inbox</TabBtn>
        <TabBtn active={tab === "sent"} onClick={() => setTab("sent")} icon={CheckCircle2}>Sent</TabBtn>
        <TabBtn active={tab === "compose"} onClick={() => setTab("compose")} icon={Send}>Compose</TabBtn>
      </div>
      {tab === "inbox" && <Inbox_ />}
      {tab === "sent" && <Sent />}
      {tab === "compose" && <Compose onSent={() => setTab("sent")} />}
    </div>
  );
};

const TabBtn = ({ active, onClick, icon: Icon, children }) => (
  <button
    onClick={onClick}
    className={`px-4 h-11 -mb-px border-b-2 text-sm font-bold inline-flex items-center gap-2 transition-colors ${
      active ? "border-[#f5b120] text-[#0a2350]" : "border-transparent text-slate-500 hover:text-[#0a2350]"
    }`}
  >
    <Icon className="h-4 w-4" /> {children}
  </button>
);

const Inbox_ = () => {
  const [rows, setRows] = useState(null);
  const [selected, setSelected] = useState(null);
  const [smtpMissing, setSmtpMissing] = useState(false);

  const load = () => api.get("/admin/mail/inbox").then((r) => setRows(r.data));
  useEffect(() => {
    load();
    // Check both legacy /admin/integrations and new /admin/integrations-v2
    Promise.all([
      api.get("/admin/integrations").catch(() => ({ data: [] })),
      api.get("/admin/integrations-v2").catch(() => ({ data: {} })),
    ]).then(([legacy, v2]) => {
      const hasLegacy = (legacy.data || []).some((x) => x.module === "smtp" && x.status === "enabled");
      const hasV2 = ((v2.data || {}).smtp || {}).enabled || ((v2.data || {}).imap || {}).enabled;
      setSmtpMissing(!(hasLegacy || hasV2));
    }).catch(() => {});
  }, []);

  const open = async (m) => {
    const { data } = await api.get(`/admin/mail/messages/${m.id}`);
    setSelected(data); load();
  };

  const star = async (m, e) => {
    e.stopPropagation();
    await api.post(`/admin/mail/messages/${m.id}/toggle-star`);
    load();
  };

  if (!rows) return <Loading />;

  return (
    <div>
      {smtpMissing && (
        <div className="mb-3 flex items-center gap-2 text-sm rounded-xl border border-amber-200 bg-amber-50 text-amber-800 px-3 py-2">
          <AlertTriangle className="h-4 w-4" /> SMTP + IMAP not configured. Inbox is showing sample messages; add <b>SMTP</b> (send) and <b>IMAP</b> (receive) under <b>Integrations</b> to enable live sync.
        </div>
      )}
      <div className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-2 p-0 divide-y divide-slate-100 max-h-[70vh] overflow-y-auto">
          {rows.length === 0 && <div className="p-6"><EmptyState title="Inbox empty" /></div>}
          {rows.map((m) => (
            <button
              key={m.id}
              onClick={() => open(m)}
              className={`text-left w-full px-4 py-3 hover:bg-slate-50 flex items-start gap-3 ${selected?.id === m.id ? "bg-[#f5b120]/10" : ""}`}
              data-testid={`mail-${m.id}`}
            >
              <button onClick={(e) => star(m, e)} className={m.starred ? "text-[#f5b120]" : "text-slate-300 hover:text-[#f5b120]"}>
                <Star className="h-4 w-4 mt-0.5" strokeWidth={m.starred ? 2.4 : 1.7} fill={m.starred ? "currentColor" : "none"} />
              </button>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className={`truncate font-semibold ${m.unread ? "text-[#0a2350]" : "text-slate-600"}`}>{m.from_name || m.from_email}</div>
                  <div className="ml-auto text-[10px] text-slate-400 whitespace-nowrap">{fullDateTime(m.received_at)}</div>
                </div>
                <div className={`text-sm truncate ${m.unread ? "font-bold text-[#0a2350]" : "text-slate-600"}`}>{m.subject}</div>
                <div className="text-xs text-slate-500 truncate">{m.preview}</div>
              </div>
              {m.unread && <span className="mt-1 h-2 w-2 rounded-full bg-[#f5b120] flex-shrink-0" />}
            </button>
          ))}
        </Card>
        <Card className="lg:col-span-3 p-6 min-h-[400px]">
          {!selected && <div className="text-center text-slate-500 pt-16 text-sm">Select a message to read</div>}
          {selected && (
            <div>
              <div className="border-b border-slate-100 pb-3 mb-4">
                <div className="text-xl font-extrabold text-[#0a2350]">{selected.subject}</div>
                <div className="mt-1 text-xs text-slate-500">From {selected.from_name} &lt;{selected.from_email}&gt; · {fullDateTime(selected.received_at)}</div>
              </div>
              <div className="text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">{selected.body}</div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
};

const Sent = () => {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/admin/mail/sent").then((r) => setRows(r.data)); }, []);
  if (!rows) return <Loading />;
  if (rows.length === 0) return <EmptyState title="No sent messages" />;
  return (
    <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
          <tr>
            <th className="px-4 py-3 text-left">To</th>
            <th className="px-4 py-3 text-left">Subject</th>
            <th className="px-4 py-3 text-left">Sent</th>
            <th className="px-4 py-3 text-left">Delivery</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              <td className="px-4 py-3 font-mono text-xs">{r.to}</td>
              <td className="px-4 py-3 font-semibold text-[#0a2350]">{r.subject}</td>
              <td className="px-4 py-3 text-slate-500 text-xs">{fullDateTime(r.sent_at)}</td>
              <td className="px-4 py-3 text-xs">
                <span className={`px-2 py-0.5 rounded-full font-bold uppercase tracking-wide text-[10px] ${r.delivered ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>{r.delivered_via}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const Compose = ({ onSent }) => {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setMsg("");
    try {
      const { data } = await api.post("/admin/mail/send", { to, subject, body });
      setMsg(`${data.delivered ? "✓ Sent" : "⏳ Queued"} via ${data.delivered_via}`);
      setTo(""); setSubject(""); setBody("");
      setTimeout(() => onSent && onSent(), 1200);
    } catch (er) {
      setMsg(er?.response?.data?.detail || "Failed to send");
    } finally { setBusy(false); }
  };

  return (
    <Card className="p-6">
      {msg && <div className="mb-3 text-sm rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 px-3 py-2">{msg}</div>}
      <form onSubmit={submit} className="space-y-4" data-testid="compose-form">
        <label>
          <div className={labelClass}>To</div>
          <input value={to} onChange={(e) => setTo(e.target.value)} className={inputClass} placeholder="client@example.com" required data-testid="compose-to" />
        </label>
        <label>
          <div className={labelClass}>Subject</div>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} className={inputClass} required data-testid="compose-subject" />
        </label>
        <label>
          <div className={labelClass}>Body</div>
          <textarea rows={10} value={body} onChange={(e) => setBody(e.target.value)} className={`${inputClass} h-auto py-2`} data-testid="compose-body" />
        </label>
        <div className="flex justify-end">
          <button type="submit" disabled={busy} className={btnPrimary} data-testid="compose-send">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send
          </button>
        </div>
      </form>
    </Card>
  );
};

export default AdminMail;
