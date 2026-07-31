import React, { useEffect, useState, useCallback } from "react";
import { Loader2, ClipboardX, CheckCircle2, XCircle, Clock } from "lucide-react";
import { PageHeader, Card } from "../ui";
import { api } from "../../../portal/api";

const StatusBadge = ({ status }) => {
  const map = {
    pending: { c: "bg-amber-100 text-amber-800", Icon: Clock, t: "Menunggu" },
    approved: { c: "bg-red-100 text-red-700", Icon: CheckCircle2, t: "Disetujui (terminated)" },
    rejected: { c: "bg-slate-100 text-slate-600", Icon: XCircle, t: "Ditolak" },
  };
  const m = map[status] || map.pending;
  const Ic = m.Icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold ${m.c}`} data-testid={`req-status-${status}`}>
      <Ic className="h-3.5 w-3.5" /> {m.t}
    </span>
  );
};

const AdminServiceRequests = () => {
  const [rows, setRows] = useState(null);
  const [filter, setFilter] = useState("pending"); // pending | all
  const [actId, setActId] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState(null);

  const load = useCallback(() => {
    setRows(null);
    api.get(`/admin/service-requests?status=all`)
      .then((r) => setRows(r.data || []))
      .catch(() => setRows([]));
  }, []);

  useEffect(() => { load(); }, [load]);

  const act = async (sid, kind) => {
    setBusy(`${sid}-${kind}`); setMsg(null);
    try {
      const { data } = await api.post(`/admin/services/${sid}/terminate-request/${kind}`, { note });
      setMsg({ ok: true, text: kind === "approve" ? "Permintaan disetujui - layanan diterminasi. Email pemberitahuan dikirim ke klien." : "Permintaan ditolak - layanan tetap aktif. Email pemberitahuan dikirim ke klien." });
      setActId(null); setNote("");
      load();
      return data;
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "Gagal memproses" });
    } finally { setBusy(""); }
  };

  const all = rows || [];
  const pending = all.filter((r) => (r.termination_request || {}).status === "pending");
  const shown = filter === "pending" ? pending : all;

  return (
    <div data-testid="admin-service-requests-page">
      <PageHeader
        title="Permintaan Pengakhiran Layanan"
        subtitle="Lacak & proses permintaan terminate dari klien. Persetujuan oleh admin / support / sales."
      />

      {msg && (
        <div className={`mb-4 text-sm rounded-xl px-4 py-2.5 border ${msg.ok ? "bg-emerald-50 border-emerald-200 text-emerald-800" : "bg-red-50 border-red-200 text-red-700"}`} data-testid="req-msg">
          {msg.text}
        </div>
      )}

      <div className="flex items-center gap-2 mb-4">
        {[
          { k: "pending", label: `Menunggu (${pending.length})` },
          { k: "all", label: `Semua (${all.length})` },
        ].map((t) => (
          <button key={t.k} onClick={() => setFilter(t.k)}
                  className={`px-3.5 py-1.5 rounded-lg text-sm font-semibold transition-colors ${filter === t.k ? "bg-[#0a2350] text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                  data-testid={`req-filter-${t.k}`}>
            {t.label}
          </button>
        ))}
        <button onClick={load} className="ml-auto text-xs text-slate-500 hover:text-[#0a2350]" data-testid="req-refresh">
          Muat ulang
        </button>
      </div>

      {rows === null ? (
        <div className="py-20 text-center text-slate-400"><Loader2 className="h-6 w-6 animate-spin inline" /></div>
      ) : shown.length === 0 ? (
        <Card className="p-12 text-center" data-testid="req-empty">
          <ClipboardX className="h-10 w-10 mx-auto text-slate-300 mb-3" />
          <div className="text-sm font-semibold text-slate-600">
            {filter === "pending" ? "Tidak ada permintaan yang menunggu" : "Belum ada permintaan pengakhiran"}
          </div>
          <p className="text-xs text-slate-400 mt-1">Permintaan dari klien akan muncul di sini untuk ditinjau.</p>
        </Card>
      ) : (
        <div className="space-y-3">
          {shown.map((r) => {
            const req = r.termination_request || {};
            const isPending = req.status === "pending";
            return (
              <Card key={r.id} className="p-4" data-testid={`req-row-${r.id}`}>
                <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-bold text-[#0a2350]">{r.product_name || r.name}</span>
                      <StatusBadge status={req.status} />
                      <span className="text-[11px] text-slate-400 uppercase tracking-widest">{r.category}</span>
                    </div>
                    <div className="text-xs text-slate-500 mt-1">
                      {r.name} · {r.user?.name} ({r.user?.email}){r.user?.company ? ` · ${r.user.company}` : ""}
                    </div>
                    <div className="mt-2 text-xs text-slate-600">
                      <span className="text-slate-400">Diminta:</span> {req.requested_at || "-"}
                      {req.reason ? <> · <span className="text-slate-400">Alasan:</span> {req.reason}</> : ""}
                    </div>
                    {req.resolved_at && (
                      <div className="mt-1 text-xs text-slate-500">
                        <span className="text-slate-400">Diproses:</span> {req.resolved_at} oleh {req.resolved_by}
                        {req.note ? ` · catatan: ${req.note}` : ""}
                      </div>
                    )}
                  </div>

                  {isPending && (
                    <div className="shrink-0">
                      {actId === r.id ? (
                        <div className="space-y-2 w-full md:w-72">
                          <input
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            placeholder="Catatan (opsional)"
                            className="w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
                            data-testid={`req-note-${r.id}`}
                          />
                          <div className="flex items-center gap-2">
                            <button onClick={() => act(r.id, "approve")} disabled={!!busy}
                                    className="flex-1 px-3 py-2 rounded-lg bg-red-600 text-white text-xs font-bold disabled:opacity-50"
                                    data-testid={`req-approve-${r.id}`}>
                              {busy === `${r.id}-approve` ? "…" : "Setujui & akhiri"}
                            </button>
                            <button onClick={() => act(r.id, "reject")} disabled={!!busy}
                                    className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-slate-600 text-xs font-bold disabled:opacity-50"
                                    data-testid={`req-reject-${r.id}`}>
                              {busy === `${r.id}-reject` ? "…" : "Tolak"}
                            </button>
                          </div>
                          <button onClick={() => { setActId(null); setNote(""); }} className="text-[11px] text-slate-400 hover:text-slate-600">
                            Batal
                          </button>
                        </div>
                      ) : (
                        <button onClick={() => { setActId(r.id); setNote(""); }}
                                className="px-4 py-2 rounded-lg bg-[#0a2350] text-white text-xs font-bold"
                                data-testid={`req-review-${r.id}`}>
                          Tinjau
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default AdminServiceRequests;
