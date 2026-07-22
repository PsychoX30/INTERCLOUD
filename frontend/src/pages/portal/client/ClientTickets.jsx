import React, { useEffect, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import { PageHeader, Card, Loading, StatusBadge, EmptyState, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { LifeBuoy, Send, Plus, MessageCircle } from "lucide-react";

const ClientTickets = () => {
  const [rows, setRows] = useState(null);
  const [creating, setCreating] = useState(false);
  const [active, setActive] = useState(null);

  const load = () => api.get("/client/tickets").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  if (!rows) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Support Tickets"
        subtitle="Direct line to our 24/7 engineering team."
        actions={<button className={btnPrimary} onClick={() => setCreating(true)} data-testid="new-ticket-btn"><Plus className="h-4 w-4" /> New Ticket</button>}
      />
      {rows.length === 0 && <EmptyState title="No tickets" body="Open your first ticket to reach the engineering team." />}
      <div className="grid gap-3">
        {rows.map((t) => (
          <button
            key={t.id}
            onClick={() => setActive(t)}
            data-testid={`ticket-${t.number}`}
            className="text-left rounded-2xl bg-white border border-slate-200 hover:border-[#f5b120] p-4 flex items-start gap-4 transition-colors"
          >
            <div className="h-11 w-11 rounded-xl bg-[#0a2350] flex items-center justify-center flex-shrink-0">
              <LifeBuoy className="h-5 w-5 text-[#f5b120]" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs font-bold text-[#f5b120]">{t.number}</span>
                <StatusBadge status={t.status} />
                <span className="text-[10px] uppercase font-bold tracking-widest text-slate-500">{t.department} · {t.priority}</span>
              </div>
              <div className="text-base font-extrabold text-[#0a2350] mt-1 truncate">{t.subject}</div>
              <div className="text-xs text-slate-500 mt-1">Updated {fullDateTime(t.updated_at)} · {t.replies.length} messages</div>
            </div>
          </button>
        ))}
      </div>

      {creating && <NewTicketModal onClose={() => setCreating(false)} onCreated={() => { setCreating(false); load(); }} />}
      {active && <TicketDetail ticket={active} onClose={() => { setActive(null); load(); }} />}
    </div>
  );
};

const NewTicketModal = ({ onClose, onCreated }) => {
  const [subject, setSubject] = useState("");
  const [department, setDepartment] = useState("technical");
  const [priority, setPriority] = useState("medium");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await api.post("/client/tickets", { subject, department, priority, message });
      onCreated();
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed to create ticket");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-lg bg-white rounded-3xl p-6" data-testid="new-ticket-form">
        <h3 className="text-xl font-extrabold text-[#0a2350]">Open a new ticket</h3>
        {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
        <div className="mt-4 space-y-3">
          <div>
            <div className={labelClass}>Subject</div>
            <input required value={subject} onChange={(e) => setSubject(e.target.value)} className={inputClass} data-testid="ticket-subject" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className={labelClass}>Department</div>
              <select value={department} onChange={(e) => setDepartment(e.target.value)} className={inputClass}>
                <option value="technical">Technical</option>
                <option value="billing">Billing</option>
                <option value="general">General</option>
                <option value="sales">Sales</option>
              </select>
            </div>
            <div>
              <div className={labelClass}>Priority</div>
              <select value={priority} onChange={(e) => setPriority(e.target.value)} className={inputClass}>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
          </div>
          <div>
            <div className={labelClass}>Message</div>
            <textarea required rows={5} value={message} onChange={(e) => setMessage(e.target.value)} className={`${inputClass} h-auto py-2`} data-testid="ticket-message" />
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary} data-testid="ticket-submit"><Send className="h-4 w-4" /> Submit</button>
        </div>
      </form>
    </div>
  );
};

const TicketDetail = ({ ticket, onClose }) => {
  const [t, setT] = useState(ticket);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (e) => {
    e.preventDefault();
    if (!reply.trim()) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/client/tickets/${t.id}/replies`, { message: reply });
      setT(data);
      setReply("");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl shadow-2xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="p-6 bg-[#0a2350] text-white">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-bold text-[#f5b120]">{t.number}</span>
            <StatusBadge status={t.status} />
          </div>
          <div className="text-xl font-extrabold mt-1">{t.subject}</div>
          <div className="text-sm text-white/70">{t.department} · {t.priority}</div>
        </div>
        <div className="p-6 overflow-y-auto flex-1 space-y-3">
          {t.replies.map((r, i) => (
            <div key={i} className={`rounded-2xl p-4 ${r.author_role === "admin" ? "bg-[#f5b120]/10 border border-[#f5b120]/30" : "bg-slate-50 border border-slate-200"}`}>
              <div className="flex items-center gap-2 text-xs">
                <span className="font-bold text-[#0a2350]">{r.author_name}</span>
                <span className="text-slate-500">· {r.author_role}</span>
                <span className="text-slate-400 ml-auto">{fullDateTime(r.created_at)}</span>
              </div>
              <div className="mt-2 text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">{r.message}</div>
            </div>
          ))}
        </div>
        <form onSubmit={send} className="p-4 border-t border-slate-100 bg-slate-50">
          <textarea rows={2} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Reply…" className={`${inputClass} h-auto py-2`} data-testid="ticket-reply-input" />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" className={btnSecondary} onClick={onClose}>Close</button>
            <button type="submit" disabled={busy || !reply.trim()} className={btnPrimary} data-testid="ticket-reply-send"><MessageCircle className="h-4 w-4" /> Reply</button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ClientTickets;
