import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Plus, X, Play, Square, CheckCircle2, Trash2, Pencil, Clock,
  MapPin, User, Search, RefreshCw, ExternalLink, CalendarClock,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "../../../portal/api";
import { useAuth } from "../../../portal/AuthContext";
import {
  PageHeader, Card, StatCard, Loading, EmptyState,
  btnPrimary, btnSecondary, btnDanger, inputClass, labelClass,
} from "../ui";

const KIND_META = {
  survey:       { label: "Survey",       chip: "bg-sky-100 text-sky-700 border-sky-200" },
  meeting:      { label: "Meeting",      chip: "bg-violet-100 text-violet-700 border-violet-200" },
  visit_dc:     { label: "Visit DC",     chip: "bg-amber-100 text-amber-800 border-amber-200" },
  installation: { label: "Instalasi",    chip: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  maintenance:  { label: "Maintenance",  chip: "bg-indigo-100 text-indigo-700 border-indigo-200" },
  content:      { label: "Content",      chip: "bg-pink-100 text-pink-700 border-pink-200" },
  followup:     { label: "Follow-up",    chip: "bg-teal-100 text-teal-700 border-teal-200" },
  other:        { label: "Lainnya",      chip: "bg-slate-100 text-slate-600 border-slate-300" },
};

const STATUS_META = {
  planned:     { label: "Planned",     chip: "bg-slate-100 text-slate-600 border-slate-300", dot: "bg-slate-400" },
  in_progress: { label: "Berjalan",    chip: "bg-blue-100 text-blue-700 border-blue-200",    dot: "bg-blue-500" },
  done:        { label: "Selesai",     chip: "bg-emerald-100 text-emerald-700 border-emerald-200", dot: "bg-emerald-500" },
  cancelled:   { label: "Dibatalkan",  chip: "bg-red-100 text-red-700 border-red-200",        dot: "bg-red-500" },
};

const EMPTY_FORM = {
  title: "", kind: "other", description: "", location: "",
  scheduled_start: "", scheduled_end: "", owner_id: "", owner_name: "",
  status: "planned", notes: "", customer_name: "", tags: [],
};

const fmt = (iso) => {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
  } catch { return iso; }
};

const fmtDuration = (min) => {
  if (min == null) return null;
  if (min < 60) return `${min} mnt`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}j ${m}m` : `${h}j`;
};

const toLocalInput = (iso) => {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return ""; }
};

const KindChip = ({ kind }) => {
  const meta = KIND_META[kind] || KIND_META.other;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-bold ${meta.chip}`}>
      {meta.label}
    </span>
  );
};

const StatusChip = ({ status }) => {
  const meta = STATUS_META[status] || STATUS_META.planned;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[11px] font-bold ${meta.chip}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  );
};

const AdminActivity = () => {
  const { user } = useAuth();
  const role = String(user?.role || "").toLowerCase();
  const isAdmin = role === "admin";
  const myId = String(user?.id || user?._id || "");

  const [rows, setRows] = useState(null);
  const [meta, setMeta] = useState({ kinds: [], statuses: [], staff: [] });
  const [filters, setFilters] = useState({ status: "", kind: "", q: "", date_from: "", date_to: "", source: "" });
  const [editing, setEditing] = useState(null); // null | "new" | row
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState("");

  const params = useMemo(() => {
    const p = {};
    Object.entries(filters).forEach(([k, v]) => { if (v) p[k] = v; });
    p.limit = 200;
    return p;
  }, [filters]);

  const load = useCallback(() => {
    api.get("/admin/activities", { params })
      .then((r) => setRows(r.data?.results || []))
      .catch((e) => {
        setRows([]);
        toast.error(e?.response?.data?.detail || "Gagal memuat activity");
      });
  }, [params]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api.get("/admin/activities/meta")
      .then((r) => setMeta(r.data || { kinds: [], statuses: [], staff: [] }))
      .catch(() => {});
  }, []);

  const stats = useMemo(() => {
    const list = rows || [];
    const today = new Date().toDateString();
    return {
      total: list.length,
      running: list.filter((r) => r.status === "in_progress").length,
      planned: list.filter((r) => r.status === "planned").length,
      doneToday: list.filter((r) => r.status === "done" && r.ended_at && new Date(r.ended_at).toDateString() === today).length,
    };
  }, [rows]);

  const openNew = () => {
    setForm({ ...EMPTY_FORM, owner_id: myId, owner_name: user?.name || user?.email || "" });
    setEditing("new");
  };

  const openEdit = (row) => {
    setForm({
      title: row.title || "",
      kind: row.kind || "other",
      description: row.description || "",
      location: row.location || "",
      scheduled_start: toLocalInput(row.scheduled_start),
      scheduled_end: toLocalInput(row.scheduled_end),
      owner_id: row.owner_id || "",
      owner_name: row.owner_name || "",
      status: row.status || "planned",
      notes: row.notes || "",
      customer_name: row.customer_name || "",
      tags: row.tags || [],
    });
    setEditing(row);
  };

  const closeModal = () => { setEditing(null); setSaving(false); };

  const submit = async (ev) => {
    ev.preventDefault();
    if (!form.title.trim()) { toast.error("Judul wajib diisi"); return; }
    setSaving(true);
    const payload = {
      ...form,
      title: form.title.trim(),
      scheduled_start: form.scheduled_start || null,
      scheduled_end: form.scheduled_end || null,
      owner_id: form.owner_id || null,
      tags: form.tags,
    };
    try {
      if (editing === "new") {
        await api.post("/admin/activities", payload);
        toast.success("Activity dibuat");
      } else {
        await api.put(`/admin/activities/${editing.id}`, payload);
        toast.success("Activity diperbarui");
      }
      closeModal();
      load();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Gagal menyimpan activity");
      setSaving(false);
    }
  };

  const act = async (row, action) => {
    setBusyId(row.id);
    try {
      const url = action === "delete"
        ? `/admin/activities/${row.id}`
        : `/admin/activities/${row.id}/${action}`;
      const res = action === "delete" ? await api.delete(url) : await api.post(url);
      if (action === "start") toast.success("Activity dimulai");
      if (action === "end") toast.success(`Selesai${res.data?.duration_minutes != null ? ` — ${fmtDuration(res.data.duration_minutes)}` : ""}`);
      if (action === "cancel") toast.success("Activity dibatalkan");
      if (action === "delete") toast.success("Activity dihapus");
      load();
    } catch (e) {
      const detail = e?.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Aksi gagal");
    } finally {
      setBusyId("");
    }
  };

  const canDelete = (row) => isAdmin || String(row.created_by || "") === myId;

  return (
    <div data-testid="activity-page">
      <PageHeader
        title="Activity"
        subtitle="Log aktivitas dan pekerjaan tim: survey, meeting, visit data center, instalasi, maintenance, konten, dan follow-up klien."
        actions={
          <>
            <button type="button" className={btnSecondary} onClick={load} data-testid="activity-refresh">
              <RefreshCw className="h-4 w-4" /> Muat ulang
            </button>
            <button type="button" className={btnPrimary} onClick={openNew} data-testid="activity-new">
              <Plus className="h-4 w-4" /> Activity baru
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Total" value={stats.total} testid="activity-stat-total" />
        <StatCard label="Berjalan" value={stats.running} tone={stats.running ? "warn" : "default"} testid="activity-stat-running" />
        <StatCard label="Rencana" value={stats.planned} testid="activity-stat-planned" />
        <StatCard label="Selesai hari ini" value={stats.doneToday} tone="good" testid="activity-stat-done-today" />
      </div>

      <Card className="p-4 mb-4">
        <div className="grid md:grid-cols-5 gap-3">
          <div className="md:col-span-2">
            <div className={labelClass}>Cari</div>
            <div className="relative mt-1">
              <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className={`${inputClass} pl-9`}
                placeholder="judul, lokasi, owner, klien"
                value={filters.q}
                onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
                data-testid="activity-search"
              />
            </div>
          </div>
          <div>
            <div className={labelClass}>Status</div>
            <select
              className={`${inputClass} mt-1`}
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
              data-testid="activity-filter-status"
            >
              <option value="">Semua</option>
              {(meta.statuses.length ? meta.statuses : Object.keys(STATUS_META)).map((s) => (
                <option key={s} value={s}>{STATUS_META[s]?.label || s}</option>
              ))}
            </select>
          </div>
          <div>
            <div className={labelClass}>Jenis</div>
            <select
              className={`${inputClass} mt-1`}
              value={filters.kind}
              onChange={(e) => setFilters((f) => ({ ...f, kind: e.target.value }))}
              data-testid="activity-filter-kind"
            >
              <option value="">Semua</option>
              {(meta.kinds.length ? meta.kinds : Object.keys(KIND_META)).map((k) => (
                <option key={k} value={k}>{KIND_META[k]?.label || k}</option>
              ))}
            </select>
          </div>
          <div>
            <div className={labelClass}>Sumber</div>
            <select
              className={`${inputClass} mt-1`}
              value={filters.source}
              onChange={(e) => setFilters((f) => ({ ...f, source: e.target.value }))}
              data-testid="activity-filter-source"
            >
              <option value="">Semua</option>
              <option value="manual">Manual</option>
              <option value="jitsi_meeting">Meeting online</option>
              <option value="sla_maintenance">Maintenance SLA</option>
              <option value="content_plan">Content plan</option>
              <option value="followup">Follow-up klien</option>
            </select>
          </div>
          <div>
            <div className={labelClass}>Dari tanggal</div>
            <input
              type="date"
              className={`${inputClass} mt-1`}
              value={filters.date_from}
              onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
              data-testid="activity-filter-from"
            />
          </div>
          <div>
            <div className={labelClass}>Sampai tanggal</div>
            <input
              type="date"
              className={`${inputClass} mt-1`}
              value={filters.date_to}
              onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
              data-testid="activity-filter-to"
            />
          </div>
        </div>
      </Card>

      {rows === null ? (
        <Loading label="Memuat activity…" />
      ) : rows.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            title="Belum ada activity"
            body="Catat survey, meeting, visit data center, instalasi, atau pekerjaan lain. Meeting online, maintenance SLA, content plan, dan follow-up klien otomatis muncul di sini."
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map((row) => {
            const busy = busyId === row.id;
            const running = row.status === "in_progress";
            const closed = row.status === "done" || row.status === "cancelled";
            return (
              <Card key={row.id} className="p-4" data-testid={`activity-row-${row.id}`}>
                <div className="flex flex-col lg:flex-row lg:items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <KindChip kind={row.kind} />
                      <StatusChip status={row.status} />
                      {row.source && row.source !== "manual" && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border border-slate-200 bg-slate-50 text-[10px] font-bold uppercase tracking-wide text-slate-500">
                          Auto · {row.source.replace(/_/g, " ")}
                        </span>
                      )}
                      {row.is_running && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-blue-700">
                          <Clock className="h-3 w-3" /> berjalan
                        </span>
                      )}
                    </div>
                    <div className="mt-1.5 text-base font-extrabold text-[#0a2350] break-words">{row.title}</div>
                    {row.description && (
                      <p className="mt-1 text-sm text-slate-600 line-clamp-3">{row.description}</p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-slate-500">
                      {row.owner_name && (
                        <span className="inline-flex items-center gap-1"><User className="h-3.5 w-3.5" />{row.owner_name}</span>
                      )}
                      {row.location && (
                        <span className="inline-flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{row.location}</span>
                      )}
                      <span className="inline-flex items-center gap-1">
                        <CalendarClock className="h-3.5 w-3.5" />
                        {row.scheduled_start ? fmt(row.scheduled_start) : fmt(row.started_at)}
                        {row.scheduled_end ? ` → ${fmt(row.scheduled_end)}` : ""}
                      </span>
                      {row.duration_minutes != null && (
                        <span className="inline-flex items-center gap-1"><Clock className="h-3.5 w-3.5" />{fmtDuration(row.duration_minutes)}</span>
                      )}
                      {row.customer_name && <span>Klien: {row.customer_name}</span>}
                      {row.tags?.length > 0 && (
                        <span className="inline-flex flex-wrap gap-1">
                          {row.tags.map((t) => (
                            <span key={t} className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 text-[10px] font-semibold">{t}</span>
                          ))}
                        </span>
                      )}
                    </div>
                    {row.started_at && (
                      <div className="mt-1 text-[11px] text-slate-400">
                        Mulai {fmt(row.started_at)}{row.ended_at ? ` · Selesai ${fmt(row.ended_at)}` : ""}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    {row.link_url && (
                      <a
                        href={row.link_url} target="_blank" rel="noreferrer"
                        className={btnSecondary} data-testid={`activity-link-${row.id}`}
                      >
                        <ExternalLink className="h-4 w-4" /> Buka
                      </a>
                    )}
                    {!closed && (
                      <button
                        type="button"
                        className={btnPrimary}
                        disabled={busy || running || row.status === "cancelled"}
                        onClick={() => act(row, "start")}
                        data-testid={`activity-start-${row.id}`}
                      >
                        <Play className="h-4 w-4" /> Start
                      </button>
                    )}
                    {row.status !== "done" && row.status !== "cancelled" && (
                      <button
                        type="button"
                        className={btnSecondary}
                        disabled={busy}
                        onClick={() => act(row, "end")}
                        data-testid={`activity-end-${row.id}`}
                      >
                        <CheckCircle2 className="h-4 w-4" /> Mark as done
                      </button>
                    )}
                    {row.status === "in_progress" && (
                      <button
                        type="button"
                        className={btnSecondary}
                        disabled={busy}
                        onClick={() => act(row, "end")}
                        data-testid={`activity-stop-${row.id}`}
                      >
                        <Square className="h-4 w-4" /> Stop
                      </button>
                    )}
                    <button
                      type="button"
                      className={btnSecondary}
                      disabled={busy}
                      onClick={() => openEdit(row)}
                      data-testid={`activity-edit-${row.id}`}
                    >
                      <Pencil className="h-4 w-4" /> Edit
                    </button>
                    {canDelete(row) && (
                      <button
                        type="button"
                        className={btnDanger}
                        disabled={busy}
                        onClick={() => {
                          if (window.confirm(`Hapus activity "${row.title}"?`)) act(row, "delete");
                        }}
                        data-testid={`activity-delete-${row.id}`}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-y-auto p-4">
          <form
            onSubmit={submit}
            className="bg-white rounded-2xl w-full max-w-2xl my-8 shadow-xl"
            data-testid="activity-modal"
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
              <div className="text-lg font-extrabold text-[#0a2350]">
                {editing === "new" ? "Activity baru" : "Edit activity"}
              </div>
              <button type="button" onClick={closeModal} className="text-slate-400 hover:text-slate-700">
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-5 grid md:grid-cols-2 gap-4">
              <div className="md:col-span-2">
                <div className={labelClass}>Judul *</div>
                <input
                  className={`${inputClass} mt-1`}
                  value={form.title}
                  onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                  placeholder="Survey jaringan cabang Bandung"
                  data-testid="activity-form-title"
                />
              </div>
              <div>
                <div className={labelClass}>Jenis</div>
                <select
                  className={`${inputClass} mt-1`}
                  value={form.kind}
                  onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}
                  data-testid="activity-form-kind"
                >
                  {Object.entries(KIND_META).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <div className={labelClass}>Status</div>
                <select
                  className={`${inputClass} mt-1`}
                  value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
                  data-testid="activity-form-status"
                >
                  {Object.entries(STATUS_META).map(([k, v]) => (
                    <option key={k} value={k}>{v.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <div className={labelClass}>Mulai terjadwal</div>
                <input
                  type="datetime-local"
                  className={`${inputClass} mt-1`}
                  value={form.scheduled_start}
                  onChange={(e) => setForm((f) => ({ ...f, scheduled_start: e.target.value }))}
                  data-testid="activity-form-start"
                />
              </div>
              <div>
                <div className={labelClass}>Selesai terjadwal</div>
                <input
                  type="datetime-local"
                  className={`${inputClass} mt-1`}
                  value={form.scheduled_end}
                  onChange={(e) => setForm((f) => ({ ...f, scheduled_end: e.target.value }))}
                  data-testid="activity-form-end"
                />
              </div>
              <div>
                <div className={labelClass}>Lokasi</div>
                <input
                  className={`${inputClass} mt-1`}
                  value={form.location}
                  onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
                  placeholder="DC Jakarta / kantor klien / online"
                  data-testid="activity-form-location"
                />
              </div>
              <div>
                <div className={labelClass}>Pelaksana</div>
                <select
                  className={`${inputClass} mt-1`}
                  value={form.owner_id}
                  onChange={(e) => {
                    const id = e.target.value;
                    const person = meta.staff.find((s) => s.id === id);
                    setForm((f) => ({ ...f, owner_id: id, owner_name: person?.name || f.owner_name }));
                  }}
                  data-testid="activity-form-owner"
                >
                  <option value="">— pilih staf —</option>
                  {meta.staff.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name || s.email} ({s.role})
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-2">
                <div className={labelClass}>Deskripsi</div>
                <textarea
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mt-1 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
                  rows={3}
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  data-testid="activity-form-description"
                />
              </div>
              <div>
                <div className={labelClass}>Klien (opsional)</div>
                <input
                  className={`${inputClass} mt-1`}
                  value={form.customer_name}
                  onChange={(e) => setForm((f) => ({ ...f, customer_name: e.target.value }))}
                  data-testid="activity-form-customer"
                />
              </div>
              <div>
                <div className={labelClass}>Tag (pisah koma)</div>
                <input
                  className={`${inputClass} mt-1`}
                  value={form.tags.join(", ")}
                  onChange={(e) => setForm((f) => ({
                    ...f,
                    tags: e.target.value.split(",").map((t) => t.trim()).filter(Boolean).slice(0, 12),
                  }))}
                  data-testid="activity-form-tags"
                />
              </div>
              <div className="md:col-span-2">
                <div className={labelClass}>Catatan</div>
                <textarea
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm mt-1 focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
                  rows={2}
                  value={form.notes}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  data-testid="activity-form-notes"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-slate-200">
              <button type="button" className={btnSecondary} onClick={closeModal}>Batal</button>
              <button type="submit" className={btnPrimary} disabled={saving} data-testid="activity-form-submit">
                {saving ? "Menyimpan…" : "Simpan"}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

export default AdminActivity;
