import React, { useEffect, useState } from "react";
import { api, fullDateTime } from "../../../portal/api";
import { PageHeader, StatusBadge, btnPrimary, btnSecondary, inputClass } from "../ui";
import { MessageCircle } from "lucide-react";
import { DataTable } from "../../../components/ui/data-table";

const AdminTickets = () => {
  const [rows, setRows] = useState(null);
  const [active, setActive] = useState(null);
  const [view, setView] = useState("active");
  const load = (v = view) => api.get(`/admin/tickets?view=${v}`).then((r) => setRows(r.data));
  useEffect(() => { setRows(null); load(view); }, [view]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns = [
    { key: "number", label: "Ticket", sortable: true, mono: true,
      render: (v) => <span className="font-mono text-xs font-bold text-[#f5b120]">{v}</span> },
    { key: "subject", label: "Subject", sortable: true,
      render: (_v, t) => (
        <>
          <div className="font-extrabold text-[#0a2350]">{t.subject}</div>
          <div className="text-xs text-slate-500">{t.user_name} · {t.user_email}</div>
          {t.related_device_name && (
            <div className="text-[10px] mt-0.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 font-mono" data-testid={`ticket-device-${t.id}`}>
              ⛁ {t.related_device_name}
            </div>
          )}
        </>
      ) },
    { key: "department", label: "Dept.", sortable: true,
      render: (v) => <span className="text-[10px] uppercase tracking-widest text-slate-500">{v}</span> },
    { key: "priority", label: "Priority", sortable: true,
      render: (v) => <span className="text-[10px] uppercase tracking-widest text-slate-500">{v}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusBadge status={v} /> },
    { key: "replies", label: "Msgs", sortable: true, align: "right",
      render: (v) => <span className="tabular-nums text-slate-500">{(v || []).length}</span> },
    { key: "updated_at", label: "Updated", sortable: true, align: "right",
      render: (v) => <span className="text-[11px] text-slate-500">{fullDateTime(v)}</span> },
  ];

  return (
    <div>
      <PageHeader title="Support Tickets" subtitle="All client tickets across departments and priorities." />
      <div className="mb-4 inline-flex rounded-full bg-slate-100 p-1" data-testid="ticket-view-tabs">
        {[["active", "Aktif"], ["archive", "Arsip (closed)"], ["all", "Semua"]].map(([k, l]) => (
          <button key={k} onClick={() => setView(k)}
            className={`px-4 py-1.5 rounded-full text-xs font-bold transition-colors ${view === k ? "bg-[#0a2350] text-white" : "text-slate-500 hover:text-[#0a2350]"}`}
            data-testid={`ticket-tab-${k}`}>
            {l}
          </button>
        ))}
      </div>
      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["number", "subject", "user_name", "user_email", "status", "priority"]}
        rowKey={(r) => r.id}
        onRowClick={(r) => setActive(r)}
        empty={{ title: "No tickets yet", hint: "Waiting for your first support ticket." }}
        testid="admin-tickets-table"
      />
      {active && <TicketDetail ticket={active} onClose={() => { setActive(null); load(); }} />}
    </div>
  );
};

const TICKET_STATUSES = [
  ["open", "Open"],
  ["awaiting_client", "Awaiting client"],
  ["awaiting_staff", "Awaiting staff"],
  ["resolved", "Resolved"],
  ["closed", "Closed"],
];

const TicketDetail = ({ ticket, onClose }) => {
  const [t, setT] = useState(ticket);
  const [reply, setReply] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const send = async (e) => {
    e.preventDefault(); if (!reply.trim()) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/admin/tickets/${t.id}/replies`, { message: reply, internal });
      setT(data); setReply(""); setInternal(false);
    } finally { setBusy(false); }
  };
  const setStatus = async (status) => {
    setBusy(true);
    try {
      const { data } = await api.put(`/admin/tickets/${t.id}/status`, { status });
      setT(data);
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center p-0 sm:p-6" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-t-3xl sm:rounded-3xl overflow-hidden max-h-[90vh] flex flex-col">
        <div className="p-6 bg-[#0a2350] text-white">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-bold text-[#f5b120]">{t.number}</span>
            <StatusBadge status={t.status} />
            <select
              value={t.status}
              onChange={(e) => setStatus(e.target.value)}
              disabled={busy}
              className="ml-auto h-8 rounded-lg bg-white/10 border border-white/20 text-white text-xs font-bold px-2 focus:outline-none [&>option]:text-[#0a2350]"
              data-testid="admin-ticket-status-select"
            >
              {TICKET_STATUSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          <div className="text-xl font-extrabold mt-1">{t.subject}</div>
          <div className="text-xs text-white/70">{t.user_name} · {t.user_email}</div>
          {t.related_device_name && (
            <div className="mt-2 inline-flex items-center gap-1.5 px-2 py-1 rounded-lg bg-white/10 border border-white/20 text-[11px] font-mono" data-testid="ticket-detail-device">
              ⛁ Perangkat terkait: <b>{t.related_device_name}</b>
            </div>
          )}
        </div>
        <div className="p-6 overflow-y-auto flex-1 space-y-3">
          {t.replies.map((r, i) => (
            <div key={i} className={`rounded-2xl p-4 ${r.internal ? "bg-indigo-50 border border-dashed border-indigo-300" : r.author_role !== "client" ? "bg-[#f5b120]/10 border border-[#f5b120]/30" : "bg-slate-50 border border-slate-200"}`}>
              <div className="flex items-center gap-2 text-xs">
                <span className="font-bold text-[#0a2350]">{r.author_name}</span>
                <span className="text-slate-500">· {r.author_role}</span>
                {r.internal && <span className="px-1.5 py-0.5 rounded bg-indigo-600 text-white text-[9px] font-bold uppercase" data-testid={`ticket-internal-badge-${i}`}>Internal</span>}
                <span className="text-slate-400 ml-auto">{fullDateTime(r.created_at)}</span>
              </div>
              <div className="mt-2 text-sm text-slate-700 whitespace-pre-wrap leading-relaxed">{r.message}</div>
            </div>
          ))}
        </div>
        <form onSubmit={send} className="p-4 border-t border-slate-100 bg-slate-50">
          <textarea rows={2} value={reply} onChange={(e) => setReply(e.target.value)} placeholder={internal ? "Catatan internal (tidak terlihat klien)…" : "Reply as staff…"} className={`${inputClass} h-auto py-2 ${internal ? "border-indigo-300 bg-indigo-50/50" : ""}`} data-testid="admin-ticket-reply" />
          <div className="mt-2 flex items-center gap-3">
            <label className="flex items-center gap-1.5 text-xs font-semibold text-indigo-700 cursor-pointer">
              <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} data-testid="admin-ticket-internal-toggle" />
              Catatan internal
            </label>
            <div className="ml-auto flex gap-2">
              <button type="button" className={btnSecondary} onClick={onClose}>Close</button>
              <button type="submit" disabled={busy || !reply.trim()} className={btnPrimary} data-testid="admin-ticket-send"><MessageCircle className="h-4 w-4" /> {internal ? "Simpan catatan" : "Reply"}</button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AdminTickets;
