import React, { useEffect, useState } from "react";
import { RefreshCw, Server, Globe2, Search, Percent, Trash2, XCircle, RotateCcw } from "lucide-react";
import { api, fullDateTime, money } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, Card } from "../ui";
import { useAuth } from "../../../portal/AuthContext";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID");

const AdminDomains = () => {
  const { user: me } = useAuth();
  const isAdmin = me?.role === "admin";
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");
  const [markup, setMarkup] = useState(7.0);
  const [markupBusy, setMarkupBusy] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  const load = async () => {
    const { data } = await api.get("/admin/domains");
    setRows(data);
  };

  const loadMarkup = async () => {
    try {
      const { data } = await api.get("/admin/domains/markup");
      if (data.markup_pct != null) setMarkup(data.markup_pct);
    } catch {}
  };

  useEffect(() => { load().catch(() => setRows([])); if (isAdmin) loadMarkup(); }, []);

  const syncPricing = async () => {
    if (busy) return;
    setBusy("pricing"); setMessage("");
    try {
      const { data } = await api.post("/admin/domains/sync-pricing");
      setMessage(`Pricing tersinkronisasi: ${data.count || 0} TLD (markup ${data.markup_pct || markup}%).`);
      if (data.markup_pct != null) setMarkup(data.markup_pct);
    } catch (e) { setMessage(e?.response?.data?.detail || "Gagal sync pricing."); }
    finally { setBusy(""); }
  };

  const saveMarkup = async () => {
    if (markupBusy) return;
    setMarkupBusy(true); setMessage("");
    try {
      const { data } = await api.post("/admin/domains/markup", { markup_pct: markup });
      setMessage(`Markup disimpan: ${data.markup_pct}% (${data.count || 0} TLD).`);
    } catch (e) { setMessage(e?.response?.data?.detail || "Gagal menyimpan markup."); }
    finally { setMarkupBusy(false); }
  };

  const syncAll = async () => {
    if (busy) return;
    setBusy("domains"); setMessage("");
    try {
      const { data } = await api.post("/admin/domains/sync-all");
      setMessage(`Status domain diperbarui: ${data.updated}; gagal: ${data.failed}.`);
      await load();
    } catch (e) { setMessage(e?.response?.data?.detail || "Gagal sync domain."); }
    finally { setBusy(""); }
  };

  const doDelete = async (d) => {
    if (busy) return;
    setBusy(`del-${d.id}`); setMessage("");
    try {
      await api.delete(`/admin/domains/${d.id}`);
      setMessage(`Domain ${d.domain} dihapus.`);
      setDeleteConfirm(null);
      await load();
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Gagal menghapus domain.");
    } finally { setBusy(""); }
  };

  const retryRegistration = async (d) => {
    if (busy) return;
    setBusy(`retry-${d.id}`); setMessage("");
    try {
      const { data } = await api.post(`/admin/domains/${d.id}/retry-registration`);
      setMessage(data.fallback
        ? `Domain ${d.domain} berhasil didaftarkan under Intercloud (customer fallback ${data.customer_id || "35284"}).`
        : `Domain ${d.domain} berhasil didaftarkan.`);
      await load();
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Retry registrasi domain gagal.");
      await load();
    } finally { setBusy(""); }
  };

  if (!rows) return <Loading />;

  const filtered = search.trim()
    ? rows.filter((d) =>
        (d.domain || "").toLowerCase().includes(search.toLowerCase()) ||
        (d.user_email || "").toLowerCase().includes(search.toLowerCase()) ||
        (d.user_name || "").toLowerCase().includes(search.toLowerCase()))
    : rows;

  const canDelete = (d) => d.status === "pending" || d.status === "cancelled";

  return (
    <div>
      <PageHeader title="Domain Management" subtitle="Kelola domain klien, status registrar, nameserver, dan sinkronisasi RDASH." />
      <div className="flex flex-wrap gap-2 mb-5">
        {isAdmin && (
          <button className={btnPrimary} onClick={syncPricing} disabled={!!busy} data-testid="sync-domain-pricing">
            <RefreshCw className={`h-4 w-4 ${busy === "pricing" ? "animate-spin" : ""}`} /> Sync Pricing RDASH
          </button>
        )}
        <button className={btnSecondary} onClick={syncAll} disabled={!!busy} data-testid="sync-domain-status">
          <Server className={`h-4 w-4 ${busy === "domains" ? "animate-spin" : ""}`} /> Sync Status Domain
        </button>
        <button className={btnSecondary} onClick={() => load()} disabled={!!busy}>Refresh</button>
      </div>
      {isAdmin && (
      <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-4">
        <Percent className="h-5 w-5 text-slate-400" />
        <span className="text-sm font-semibold text-slate-700">Markup Harga Domain:</span>
        <input
          type="number"
          className="w-20 rounded border border-slate-200 px-2 py-1 text-sm text-center"
          value={markup}
          min={0}
          max={100}
          step={0.1}
          onChange={(e) => setMarkup(parseFloat(e.target.value) || 0)}
          data-testid="domain-markup-input"
        />
        <span className="text-sm text-slate-500">%</span>
        <button className={btnPrimary} onClick={saveMarkup} disabled={markupBusy} data-testid="save-domain-markup">
          Simpan Markup
        </button>
        <span className="text-xs text-slate-400">Harga jual = harga reseller + markup ini. Sync pricing akan otomatis pakai nilai terbaru.</span>
      </div>
      )}
      {message && <div className="mb-4 rounded-lg bg-slate-100 px-4 py-3 text-sm text-slate-700">{message}</div>}
      <div className="mb-4 flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            className="w-full pl-10 pr-3 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#f5b120]/40"
            placeholder="Cari domain, klien, atau email..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>
      {filtered.length === 0 && <EmptyState title="Belum ada domain" />}
      <div className="grid gap-3">
        {filtered.map((d) => (
          <Card key={d.id} className="p-4" data-testid={`admin-domain-${d.id}`}>
            <div className="flex flex-col md:flex-row md:items-center gap-4">
              <Globe2 className="h-8 w-8 text-[#f5b120] shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-extrabold text-[#0a2350]">{d.domain}</span>
                  <StatusBadge status={d.status} />
                  {d.parked && <span className="text-[10px] font-bold uppercase bg-slate-100 text-slate-600 rounded-full px-2 py-0.5">Parked</span>}
                  {d.forwarded && <span className="text-[10px] font-bold uppercase bg-blue-100 text-blue-700 rounded-full px-2 py-0.5">Forwarded</span>}
                  {d.pending_renewal && <span className="text-[10px] font-bold uppercase bg-amber-100 text-amber-700 rounded-full px-2 py-0.5">Renewal pending</span>}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {(d.user_name || d.user_email) ? `${d.user_name || ""} ${d.user_email ? "· " + d.user_email : ""}` : "—"} · {d.registrar || "RNA"} · dibuat {fullDateTime(d.created_at)}
                  {d.expires_at && ` · expires ${d.expires_at}`}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  NS: {(d.nameservers || []).join(", ") || "belum tersedia"}
                </div>
                {d.cancelled_at && (
                  <div className="mt-1 text-xs text-red-600">
                    Dibatalkan {d.cancelled_at}: {d.cancelled_reason || "(tanpa alasan)"}
                  </div>
                )}
              </div>
              <div className="text-right shrink-0">
                <div className="font-bold text-[#0a2350]">{money(d.price || 0)}</div>
                <div className="text-[10px] text-slate-500">{d.years || 1} tahun</div>
              </div>
              {(d.status === "pending" || canDelete(d)) && (
                <div className="shrink-0 flex flex-wrap justify-end gap-2">
                  {d.status === "pending" && (
                    <button
                      className="text-[10px] font-bold px-2 py-1.5 rounded border border-amber-300 text-amber-700 hover:bg-amber-50 inline-flex items-center gap-1"
                      onClick={() => retryRegistration(d)}
                      disabled={!!busy}
                      data-testid={`domain-retry-registration-${d.id}`}
                    >
                      <RotateCcw className={`h-3 w-3 ${busy === `retry-${d.id}` ? "animate-spin" : ""}`} />
                      {busy === `retry-${d.id}` ? "Memproses..." : "Retry Registrasi"}
                    </button>
                  )}
                  {canDelete(d) && (
                  <div>
                  {deleteConfirm === d.id ? (
                    <div className="flex items-center gap-1.5">
                      <button
                        className="text-[10px] font-bold px-2 py-1.5 rounded bg-red-600 text-white hover:bg-red-700"
                        onClick={() => doDelete(d)}
                        disabled={!!busy}
                        data-testid={`domain-delete-confirm-${d.id}`}
                      >
                        {busy === `del-${d.id}` ? "..." : "Ya, hapus"}
                      </button>
                      <button
                        className="text-[10px] font-bold px-2 py-1.5 rounded border border-slate-200 text-slate-600"
                        onClick={() => setDeleteConfirm(null)}
                        data-testid={`domain-delete-cancel-${d.id}`}
                      >
                        Tidak
                      </button>
                    </div>
                  ) : (
                    <button
                      className="text-[10px] font-bold px-2 py-1.5 rounded border border-red-200 text-red-600 hover:bg-red-50 inline-flex items-center gap-1"
                      onClick={() => setDeleteConfirm(d.id)}
                      data-testid={`domain-delete-btn-${d.id}`}
                    >
                      <Trash2 className="h-3 w-3" /> Hapus
                    </button>
                  )}
                  </div>
                  )}
                </div>
              )}
            </div>
            {d.provision_note && <div className="mt-3 border-t pt-2 text-xs text-slate-500">{d.provision_note}</div>}
          </Card>
        ))}
      </div>
    </div>
  );
};

export default AdminDomains;