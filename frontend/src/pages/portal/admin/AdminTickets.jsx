import React, { useEffect, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, inputClass } from "../ui";
import { MessageCircle } from "lucide-react";

const AdminTickets = () => {
  const [rows, setRows] = useState(null);
  const [active, setActive] = useState(null);
  const load = () => api.get("/admin/tickets").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;
  return (
    <div>
      <PageHeader title="Support Tickets" subtitle="All client tickets across departments and priorities." />
      {rows.length === 0 && <EmptyState title="No tickets yet" />}
      <div className="grid gap-3">
        {rows.map((t) => (
          <button
            key={t.id}
            onClick={() => setActive(t)}
            data-testid={`admin-ticket-${t.number}`}
            className="text-left rounded-2xl bg-white border border-slate-200 hover:border-[#f5b120] p-4 transition-colors"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-mono text-xs font-bold text-[#f5b120]">{t.number}</span>
              <StatusBadge status={t.status} />
              <span className="text-[10px] uppercase tracking-widest text-slate-500">{t.department} · {t.priority}</span>
              <span className="ml-auto text-[11px] text-slate-500">{fullDateTime(t.updated_at)}</span>
            </div>
            <div className="mt-1 text-base font-extrabold text-[#0a2350]">{t.subject}</div>
            <div className="text-xs text-slate-500">
              {t.user_name} · {t.user_email} · {t.replies.length} message(s)
            </div>
          </button>
        ))}
      </div>
      {active && <TicketDetail ticket={active} onClose={() => { setActive(null); load(); }} />}
    </div>
  );
};

const TicketDetail = ({ ticket, onClose }) => {
  const [t, setT] = useState(ticket);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async (e) => {
    e.preventDefault(); if (!reply.trim()) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/admin/tickets/${t.id}/replies`, { message: reply });
      setT(data); setReply("");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="p-6 bg-[#0a2350] text-white">
          <div className="flex items-center gap-2"><span className="font-mono text-xs font-bold text-[#f5b120]">{t.number}</span><StatusBadge status={t.status} /></div>
          <div className="text-xl font-extrabold mt-1">{t.subject}</div>
          <div className="text-xs text-white/70">{t.user_name} · {t.user_email}</div>
        </div>
        <div className="p-6 overflow-y-auto flex-1 space-y-3">
          {t.replies.map((r, i) => (
            <div key={i} className={`rounded-2xl p-4 ${r.author_role !== "client" ? "bg-[#f5b120]/10 border border-[#f5b120]/30" : "bg-slate-50 border border-slate-200"}`}>
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
          <textarea rows={2} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="Reply as staff…" className={`${inputClass} h-auto py-2`} data-testid="admin-ticket-reply" />
          <div className="mt-2 flex justify-end gap-2">
            <button type="button" className={btnSecondary} onClick={onClose}>Close</button>
            <button type="submit" disabled={busy || !reply.trim()} className={btnPrimary} data-testid="admin-ticket-send"><MessageCircle className="h-4 w-4" /> Reply</button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AdminTickets;
