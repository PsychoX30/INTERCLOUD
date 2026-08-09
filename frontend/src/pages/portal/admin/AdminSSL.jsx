import React, { useEffect, useState } from "react";
import { api, fullDateTime, money } from "../../../portal/api";
import { PageHeader, Loading, EmptyState, StatusBadge, Card, btnPrimary, btnSecondary } from "../ui";
import { ShieldCheck, Search } from "lucide-react";

const idr = (v) => "Rp " + Number(v || 0).toLocaleString("id-ID");

const AdminSSL = () => {
  const [orders, setOrders] = useState(null);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    try {
      const { data } = await api.get("/admin/ssl/orders");
      setOrders(data.orders || []);
    } catch { setOrders([]); }
  };

  useEffect(() => { load(); }, []);

  const updateStatus = async (id, status) => {
    setBusy(id); setMessage("");
    try {
      await api.put(`/admin/ssl/orders/${id}/status`, { status });
      setMessage(`Status SSL order diperbarui ke ${status}`);
      load();
    } catch (e) {
      setMessage(e?.response?.data?.detail || "Gagal memperbarui status");
    } finally { setBusy(""); }
  };

  const filtered = (orders || []).filter((o) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return o.domain.toLowerCase().includes(q) || o.product_name.toLowerCase().includes(q) || o.status.includes(q);
  });

  return (
    <div>
      <PageHeader title="SSL Orders" subtitle="Kelola semua order SSL certificate dari klien." />

      {message && (
        <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700" data-testid="ssl-admin-message">
          {message}
        </div>
      )}

      <div className="flex gap-2 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none"
            placeholder="Cari domain, produk, status..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="ssl-admin-search"
          />
        </div>
      </div>

      {orders === null && <Loading />}
      {orders !== null && filtered.length === 0 && (
        <Card className="p-8 text-center text-sm text-slate-500" data-testid="ssl-admin-empty">
          Belum ada order SSL.
        </Card>
      )}

      <div className="space-y-3">
        {filtered.map((o) => (
          <Card key={o.id} className="p-4" data-testid={`ssl-admin-order-${o.id}`}>
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-lg bg-emerald-100 flex items-center justify-center shrink-0">
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-bold text-[#0a2350]">{o.domain}</div>
                <div className="text-[11px] text-slate-500">
                  {o.product_name} &middot; {o.period_months} bln &middot; {fullDateTime(o.created_at)}
                </div>
                {o.provider_order_id && (
                  <div className="text-[11px] text-slate-400 font-mono">Ref: {o.provider_order_id}</div>
                )}
                {o.provision_note && (
                  <div className="mt-1 text-[11px] text-amber-600">{o.provision_note}</div>
                )}
              </div>
              <div className="text-right">
                <div className="text-sm font-bold text-[#0a2350]">{idr(o.price)}</div>
                <StatusBadge status={o.status} />
              </div>
              <div className="flex flex-col gap-1 ml-2">
                <select
                  className="text-[11px] font-bold rounded-md border border-slate-200 px-2 py-1 outline-none focus:border-[#f5b120]"
                  value={o.status}
                  onChange={(e) => updateStatus(o.id, e.target.value)}
                  disabled={busy === o.id}
                  data-testid={`ssl-admin-status-${o.id}`}
                >
                  <option value="pending">Pending</option>
                  <option value="active">Active</option>
                  <option value="failed">Failed</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
};

export default AdminSSL;