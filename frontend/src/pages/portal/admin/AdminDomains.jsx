import React, { useEffect, useState } from "react";
import { RefreshCw, Server, Globe2, Search } from "lucide-react";
import { api, fullDateTime, money } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, Card } from "../ui";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID");

const AdminDomains = () => {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [search, setSearch] = useState("");

  const load = async () => {
    const { data } = await api.get("/admin/domains");
    setRows(data);
  };

  useEffect(() => { load().catch(() => setRows([])); }, []);

  const syncPricing = async () => {
    if (busy) return;
    setBusy("pricing"); setMessage("");
    try {
      const { data } = await api.post("/admin/domains/sync-pricing");
      setMessage(`Pricing tersinkronisasi: ${data.count || 0} TLD.`);
    } catch (e) { setMessage(e?.response?.data?.detail || "Gagal sync pricing."); }
    finally { setBusy(""); }
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

  if (!rows) return <Loading />;

  const filtered = search.trim()
    ? rows.filter((d) =>
        (d.domain || "").toLowerCase().includes(search.toLowerCase()) ||
        (d.user_email || "").toLowerCase().includes(search.toLowerCase()) ||
        (d.user_name || "").toLowerCase().includes(search.toLowerCase()))
    : rows;

  return (
    <div>
      <PageHeader title="Domain Management" subtitle="Kelola domain klien, status registrar, nameserver, dan sinkronisasi RDASH." />
      <div className="flex flex-wrap gap-2 mb-5">
        <button className={btnPrimary} onClick={syncPricing} disabled={!!busy} data-testid="sync-domain-pricing">
          <RefreshCw className={`h-4 w-4 ${busy === "pricing" ? "animate-spin" : ""}`} /> Sync Pricing RDASH
        </button>
        <button className={btnSecondary} onClick={syncAll} disabled={!!busy} data-testid="sync-domain-status">
          <Server className={`h-4 w-4 ${busy === "domains" ? "animate-spin" : ""}`} /> Sync Status Domain
        </button>
        <button className={btnSecondary} onClick={() => load()} disabled={!!busy}>Refresh</button>
      </div>
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
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {(d.user_name || d.user_email) ? `${d.user_name || ""} ${d.user_email ? "· " + d.user_email : ""}` : "—"} · {d.registrar || "RNA"} · dibuat {fullDateTime(d.created_at)}
                  {d.expires_at && ` · expires ${d.expires_at}`}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  NS: {(d.nameservers || []).join(", ") || "belum tersedia"}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-bold text-[#0a2350]">{money(d.price || 0)}</div>
                <div className="text-[10px] text-slate-500">{d.years || 1} tahun</div>
              </div>
            </div>
            {d.provision_note && <div className="mt-3 border-t pt-2 text-xs text-slate-500">{d.provision_note}</div>}
          </Card>
        ))}
      </div>
    </div>
  );
};

export default AdminDomains;
