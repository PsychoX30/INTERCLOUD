import React, { useEffect, useMemo, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, btnDanger, inputClass, labelClass } from "../ui";
import { ChevronLeft, ChevronRight, Plus, X, Newspaper, Megaphone, Share2 } from "lucide-react";
import { toast } from "sonner";
import {
  startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  addMonths, addDays, format, isSameMonth, isSameDay, parseISO,
} from "date-fns";

const TYPE_META = {
  article:     { label: "Article",     Icon: Newspaper, chip: "bg-sky-100 text-sky-700 border-sky-200" },
  campaign:    { label: "Campaign",    Icon: Megaphone, chip: "bg-amber-100 text-amber-700 border-amber-200" },
  social_post: { label: "Social Post", Icon: Share2,    chip: "bg-emerald-100 text-emerald-700 border-emerald-200" },
};
const STATUS_DOT = { draft: "bg-slate-400", scheduled: "bg-amber-500", published: "bg-emerald-500" };

const AdminContentCalendar = () => {
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null); // null | "new" | entry

  const load = async () => {
    const from = format(startOfWeek(startOfMonth(month), { weekStartsOn: 1 }), "yyyy-MM-dd");
    const to = format(endOfWeek(endOfMonth(month), { weekStartsOn: 1 }), "yyyy-MM-dd");
    const r = await api.get(`/admin/content-calendar?date_from=${from}&date_to=${to}`);
    setRows(r.data || []);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [month]);

  const days = useMemo(() => {
    const start = startOfWeek(startOfMonth(month), { weekStartsOn: 1 });
    const end = endOfWeek(endOfMonth(month), { weekStartsOn: 1 });
    const out = [];
    for (let d = start; d <= end; d = addDays(d, 1)) out.push(d);
    return out;
  }, [month]);

  const byDay = useMemo(() => {
    const map = {};
    (rows || []).forEach((e) => {
      try {
        const k = format(parseISO(e.scheduled_at), "yyyy-MM-dd");
        (map[k] = map[k] || []).push(e);
      } catch {}
    });
    return map;
  }, [rows]);

  if (rows === null) return <Loading label="Loading content calendar…" />;

  return (
    <div data-testid="content-calendar-page">
      <PageHeader
        title="Content Calendar"
        subtitle="Plan articles, campaigns, and social posts. Publishing an article automatically marks its calendar entry as published."
        actions={
          <button className={btnPrimary} onClick={() => setEditing("new")} data-testid="calendar-new-btn">
            <Plus className="h-4 w-4" /> Plan content
          </button>
        }
      />

      <Card className="p-4">
        <div className="flex items-center justify-between mb-4">
          <button className={btnSecondary} onClick={() => setMonth(addMonths(month, -1))} data-testid="calendar-prev">
            <ChevronLeft className="h-4 w-4" /> Prev
          </button>
          <div className="text-lg font-extrabold text-[#0a2350]" data-testid="calendar-month-label">{format(month, "MMMM yyyy")}</div>
          <button className={btnSecondary} onClick={() => setMonth(addMonths(month, 1))} data-testid="calendar-next">
            Next <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-7 gap-px bg-slate-200 rounded-xl overflow-hidden text-[10px] font-bold uppercase tracking-widest text-slate-500">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
            <div key={d} className="bg-slate-50 px-2 py-2 text-center">{d}</div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-px bg-slate-200 rounded-b-xl overflow-hidden">
          {days.map((d) => {
            const k = format(d, "yyyy-MM-dd");
            const entries = byDay[k] || [];
            const today = isSameDay(d, new Date());
            return (
              <div key={k} className={`bg-white min-h-[92px] p-1.5 ${!isSameMonth(d, month) ? "opacity-40" : ""}`} data-testid={`calendar-day-${k}`}>
                <div className={`text-[11px] font-bold mb-1 ${today ? "inline-flex h-5 w-5 items-center justify-center rounded-full bg-[#f5b120] text-[#0a2350]" : "text-slate-500"}`}>
                  {format(d, "d")}
                </div>
                <div className="space-y-1">
                  {entries.map((e) => {
                    const meta = TYPE_META[e.type] || TYPE_META.article;
                    return (
                      <button key={e.id} onClick={() => setEditing(e)}
                              className={`w-full text-left px-1.5 py-1 rounded-md border text-[10px] font-semibold truncate flex items-center gap-1 ${meta.chip} focus-visible:ring-2 focus-visible:ring-[#f5b120]`}
                              title={`${meta.label} · ${e.status} - ${e.title}`}
                              data-testid={`calendar-entry-${e.id}`}>
                        <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${STATUS_DOT[e.status] || "bg-slate-400"}`} />
                        <span className="truncate">{e.title}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {rows.length === 0 && (
          <div className="mt-4">
            <EmptyState
              title="Nothing planned this month"
              body="Plan your first article, campaign, or social post - the team sees everything in one calendar."
            />
            <div className="text-center mt-3">
              <button className={btnPrimary} onClick={() => setEditing("new")} data-testid="calendar-empty-new">
                <Plus className="h-4 w-4" /> Plan your first content
              </button>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-4 mt-4 text-[11px] text-slate-500">
          {Object.entries(STATUS_DOT).map(([s, cls]) => (
            <span key={s} className="inline-flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${cls}`} /> {s}</span>
          ))}
        </div>
      </Card>

      {editing && (
        <EntryModal
          entry={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
};

const EntryModal = ({ entry, onClose, onDone }) => {
  const [f, setF] = useState({
    title: entry?.title || "",
    type: entry?.type || "article",
    status: entry?.status || "draft",
    scheduled_at: entry?.scheduled_at ? entry.scheduled_at.slice(0, 10) : format(new Date(), "yyyy-MM-dd"),
    notes: entry?.notes || "",
  });
  const [busy, setBusy] = useState(false);
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload = { ...f, scheduled_at: `${f.scheduled_at}T09:00:00` };
      if (entry) {
        await api.put(`/admin/content-calendar/${entry.id}`, payload);
        toast.success("Calendar entry updated");
      } else {
        await api.post("/admin/content-calendar", payload);
        toast.success("Content planned");
      }
      onDone();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Save failed");
    } finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm("Delete this calendar entry?")) return;
    await api.delete(`/admin/content-calendar/${entry.id}`);
    toast.success("Calendar entry deleted");
    onDone();
  };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={save} onClick={(e) => e.stopPropagation()} className="w-full max-w-lg bg-white rounded-3xl p-6" data-testid="calendar-entry-modal">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-extrabold text-[#0a2350]">{entry ? "Edit planned content" : "Plan content"}</h3>
          <button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
        </div>
        <label className="block mb-3"><div className={labelClass}>Title *</div>
          <input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={inputClass} data-testid="calendar-title-input" /></label>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label><div className={labelClass}>Type</div>
            <select value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })} className={inputClass} data-testid="calendar-type-select">
              <option value="article">Article</option>
              <option value="campaign">Campaign</option>
              <option value="social_post">Social Post</option>
            </select></label>
          <label><div className={labelClass}>Status</div>
            <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} className={inputClass} data-testid="calendar-status-select">
              <option value="draft">Draft</option>
              <option value="scheduled">Scheduled</option>
              <option value="published">Published</option>
            </select></label>
        </div>
        <label className="block mb-3"><div className={labelClass}>Date</div>
          <input type="date" value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} className={inputClass} data-testid="calendar-date-input" /></label>
        <label className="block mb-4"><div className={labelClass}>Notes</div>
          <textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} className={inputClass} /></label>
        <div className="flex justify-between">
          {entry ? <button type="button" className={btnDanger} onClick={remove} data-testid="calendar-delete-btn">Delete</button> : <span />}
          <div className="flex gap-2">
            <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
            <button type="submit" className={btnPrimary} disabled={busy} data-testid="calendar-save-btn">
              {busy ? "Saving…" : entry ? "Save changes" : "Plan content"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};

export default AdminContentCalendar;
