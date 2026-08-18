import React, { useEffect, useMemo, useState } from "react";
import { api, money, shortDate, fullDateTime } from "../../../portal/api";
import { PageHeader } from "../ui";
import { DataTable } from "../../../components/ui/data-table";
import TablePager from "./TablePager";
import {
  Download,
  Eye,
  FileSpreadsheet,
  Search,
  X,
  Receipt,
} from "lucide-react";

const STATUS_OPTIONS = [
  { value: "", label: "Semua status" },
  { value: "paid", label: "Paid" },
  { value: "unpaid", label: "Unpaid" },
  { value: "pending", label: "Pending" },
  { value: "failed", label: "Failed" },
  { value: "refunded", label: "Refunded" },
  { value: "cancelled", label: "Cancelled" },
];

const METHOD_OPTIONS = [
  { value: "", label: "Semua metode" },
  { value: "bank_transfer", label: "Bank Transfer" },
  { value: "duitku", label: "Duitku" },
  { value: "xendit", label: "Xendit" },
  { value: "credit_note", label: "Credit Note" },
  { value: "manual", label: "Manual" },
];

const STATUS_COLORS = {
  paid: "bg-emerald-100 text-emerald-700",
  unpaid: "bg-amber-100 text-amber-700",
  pending: "bg-slate-100 text-slate-600",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-indigo-100 text-indigo-700",
  cancelled: "bg-slate-200 text-slate-500",
};

const StatusPill = ({ status }) => (
  <span
    className={`inline-block text-[11px] font-bold uppercase px-2 py-0.5 rounded-full ${
      STATUS_COLORS[status] || "bg-slate-100 text-slate-600"
    }`}
  >
    {status || "-"}
 </span>
);

const METHOD_LABELS = {
  bank_transfer: "Bank Transfer",
  duitku: "Duitku",
  xendit: "Xendit",
  credit_note: "Credit Note",
  manual: "Manual",
  auto: "Auto",
};

const InvoicePreviewModal = ({ invoiceId, onClose }) => {
  const [html, setHtml] = useState(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!invoiceId) return;
    let alive = true;
    api
      .get(`/documents/invoice/${invoiceId}`, { params: { format: "html" }, responseType: "text" })
      .then((r) => {
        if (!alive) return;
        setHtml(r.data);
      })
      .catch((e) => setErr(e?.response?.data?.detail || "Gagal memuat invoice"));
    return () => {
      alive = false;
    };
  }, [invoiceId]);

  return (
    <div
      className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-3"
      onClick={onClose}
      data-testid="tx-invoice-modal"
    >
      <div
        className="bg-white rounded-2xl w-full max-w-5xl max-h-[92vh] flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <Receipt className="h-4 w-4 text-[#0a2350]" />
            <div className="font-bold text-[#0a2350]">Invoice Preview</div>
         </div>
          <button className="text-slate-500 hover:text-red-600" onClick={onClose} data-testid="tx-invoice-close">
            <X className="h-5 w-5" />
         </button>
       </div>
        <div className="flex-1 overflow-auto bg-slate-100">
          {err && (
            <div className="p-6 text-sm text-red-700 bg-red-50 border-b border-red-200">{err}</div>
          )}
          {!err && !html && (
            <div className="p-10 text-center text-sm text-slate-500">Memuat invoice…</div>
          )}
          {html && (
            <iframe
              title="invoice-preview"
              srcDoc={html}
              className="w-full min-h-[80vh] bg-white"
              data-testid="tx-invoice-iframe"
            />
          )}
       </div>
     </div>
   </div>
  );
};

const AdminTransactions = () => {
  const [rows, setRows] = useState(null);
  const [summary, setSummary] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [filters, setFilters] = useState({
    start: "",
    end: "",
    status: "",
    method: "",
    search: "",
  });
  const [previewId, setPreviewId] = useState(null);
  const [busyExport, setBusyExport] = useState(false);
  const [exportErr, setExportErr] = useState("");

  const queryString = useMemo(() => {
    const p = { paginate: true, limit, skip: page * limit };
    if (filters.start) p.start = `${filters.start}T00:00:00`;
    if (filters.end) p.end = `${filters.end}T23:59:59`;
    if (filters.status) p.status = filters.status;
    if (filters.method) p.method = filters.method;
    if (filters.search) p.search = filters.search;
    return p;
  }, [filters, page, limit]);

  const load = () => {
    api
      .get("/admin/transactions", { params: queryString })
      .then((r) => {
        setRows(r.data?.items || []);
        setTotal(r.data?.total || 0);
      });
    api.get("/admin/transactions/summary", { params: queryString }).then((r) => setSummary(r.data));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryString]);

  const downloadInvoicePdf = async (invoiceId, number) => {
    try {
      const r = await api.get(`/documents/invoice/${invoiceId}`, {
        params: { format: "pdf" },
        responseType: "blob",
      });
      const blobUrl = URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `Invoice-${number || invoiceId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal mengunduh PDF");
    }
  };

  const exportXlsx = async () => {
    setBusyExport(true);
    setExportErr("");
    try {
      const r = await api.get("/admin/transactions/export/xlsx", {
        params: queryString,
        responseType: "blob",
      });
      const cd = r.headers?.["content-disposition"] || "";
      const match = /filename="?([^"]+)"?/.exec(cd);
      const filename = match ? match[1] : `Transaction_Ledger_${Date.now()}.xlsx`;
      const blobUrl = URL.createObjectURL(
        new Blob([r.data], {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
      );
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
    } catch (e) {
      setExportErr(e?.response?.data?.detail || "Gagal export XLSX");
    } finally {
      setBusyExport(false);
    }
  };

  const columns = [
    { key: "invoice_number", label: "Invoice #", sortable: true,
      render: (v, r) => (
        <div className="flex items-center gap-2">
          <span className="font-mono font-bold text-[#0a2350]">{v || "-"}</span>
          {r.invoice_id && (
            <span className="inline-flex items-center gap-1 text-[11px]" data-testid={`tx-row-${r.id}`}>
              <button
                className="text-slate-500 hover:text-[#f5b120]"
                title="Preview invoice"
                onClick={(e) => { e.stopPropagation(); setPreviewId(r.invoice_id); }}
                data-testid={`tx-preview-${r.id}`}
              >
                <Eye className="h-3.5 w-3.5" />
             </button>
              <button
                className="text-slate-500 hover:text-[#f5b120]"
                title="Download invoice PDF"
                onClick={(e) => { e.stopPropagation(); downloadInvoicePdf(r.invoice_id, r.invoice_number); }}
                data-testid={`tx-pdf-${r.id}`}
              >
                <Download className="h-3.5 w-3.5" />
             </button>
           </span>
          )}
       </div>
      ) },
    { key: "customer_name", label: "Customer", sortable: true,
      render: (v) => <span className="font-semibold text-[#0a2350]">{v || "-"}</span> },
    { key: "amount", label: "Amount", sortable: true, align: "right",
      render: (v) => <span className="font-extrabold text-[#0a2350]">{money(v)}</span> },
    { key: "method", label: "Method", sortable: true,
      render: (v) => <span className="text-slate-600">{METHOD_LABELS[v] || v || "-"}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusPill status={v} /> },
    { key: "reference", label: "Reference", sortable: true, mono: true,
      render: (v) => v ? (
        <span className="font-mono text-xs text-[#0a2350]" title={v}>{String(v).slice(0, 18)}{String(v).length > 18 ? "…" : ""}</span>
      ) : <span className="text-slate-400 text-xs">-</span> },
    { key: "paid_at", label: "Paid At", sortable: true,
      render: (v) => <span className="text-slate-500">{v ? fullDateTime(v) : "-"}</span> },
    { key: "verified", label: "Verified", sortable: true,
      render: (v, r) => v ? (
        <span className="inline-flex flex-col" title={r.verified_at ? `Verified ${fullDateTime(r.verified_at)}` : "Verified"}>
          <span className="text-emerald-700 text-xs font-bold">Verified</span>
          {r.verified_at && <span className="text-slate-400 text-[10px]">{shortDate(r.verified_at)}</span>}
       </span>
      ) : <span className="text-slate-400 text-xs">—</span> },
    { key: "notes", label: "Notes", sortable: false,
      render: (v) => <span className="text-xs text-slate-500 max-w-[16ch] truncate inline-block" title={v}>{v || "-"}</span> },
  ];

  return (
    <div>
      <PageHeader
        title="Transaction Ledger"
        subtitle="Payment lifecycle view for reconciliation. Filter, inspect, and export to Excel."
        actions={
          <button
            className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold px-4 h-10 transition-colors disabled:opacity-50"
            onClick={exportXlsx}
            disabled={busyExport}
            data-testid="tx-export-xlsx"
          >
            <FileSpreadsheet className="h-4 w-4" />
            {busyExport ? "Mengekspor…" : "Export XLSX"}
         </button>
        }
      />

      <div className="bg-white border border-slate-200 rounded-2xl p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          <label className="md:col-span-2">
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Cari customer / invoice / referensi</div>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
              <input
                type="text"
                className="w-full h-10 rounded-lg border border-slate-300 pl-9 pr-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
                placeholder="Nama, nomor invoice, referensi…"
                value={filters.search}
                onChange={(e) => { setPage(0); setFilters({ ...filters, search: e.target.value }); }}
                data-testid="tx-search"
              />
           </div>
         </label>
          <label>
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Status</div>
            <select
              className="w-full h-10 rounded-lg border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
              value={filters.status}
              onChange={(e) => { setPage(0); setFilters({ ...filters, status: e.target.value }); }}
              data-testid="tx-filter-status"
            >
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
           </select>
         </label>
          <label>
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Metode</div>
            <select
              className="w-full h-10 rounded-lg border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
              value={filters.method}
              onChange={(e) => { setPage(0); setFilters({ ...filters, method: e.target.value }); }}
              data-testid="tx-filter-method"
            >
              {METHOD_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
           </select>
         </label>
          <div className="grid grid-cols-2 gap-2">
            <label>
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Dari</div>
              <input
                type="date"
                className="w-full h-10 rounded-lg border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
                value={filters.start}
                onChange={(e) => { setPage(0); setFilters({ ...filters, start: e.target.value }); }}
                data-testid="tx-filter-start"
              />
           </label>
            <label>
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">Sampai</div>
              <input
                type="date"
                className="w-full h-10 rounded-lg border border-slate-300 px-3 text-sm focus:outline-none focus:ring-2 focus:ring-[#f5b120] focus:border-[#f5b120]"
                value={filters.end}
                onChange={(e) => { setPage(0); setFilters({ ...filters, end: e.target.value }); }}
                data-testid="tx-filter-end"
              />
           </label>
         </div>
       </div>
        {exportErr && (
          <div className="mt-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{exportErr}</div>
        )}
     </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-emerald-700">Paid</div>
            <div className="text-xl font-extrabold text-[#0a2350]">{money(summary.paid_amount)}</div>
            <div className="text-xs text-slate-500">{summary.paid_count || 0} transaksi</div>
         </div>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-amber-700">Outstanding</div>
            <div className="text-xl font-extrabold text-[#0a2350]">{money(summary.outstanding_amount)}</div>
            <div className="text-xs text-slate-500">Belum dibayar</div>
         </div>
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Refunded</div>
            <div className="text-xl font-extrabold text-[#0a2350]">{money((summary.by_status?.refunded || {}).amount || 0)}</div>
            <div className="text-xs text-slate-500">{(summary.by_status?.refunded || {}).count || 0} transaksi</div>
         </div>
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Cancelled</div>
            <div className="text-xl font-extrabold text-[#0a2350]">{money((summary.by_status?.cancelled || {}).amount || 0)}</div>
            <div className="text-xs text-slate-500">{(summary.by_status?.cancelled || {}).count || 0} transaksi</div>
         </div>
       </div>
      )}

      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["invoice_number", "customer_name", "method", "status", "notes", "reference"]}
        rowKey={(r) => r.id}
        empty={{ title: "Belum ada transaksi", hint: "Transaksi muncul saat invoice dibuat / dibayar / di-refund." }}
        testid="admin-transactions-table"
      />

      {rows !== null && total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => {
            setLimit(l);
            setPage(0);
          }}
          testid="admin-transactions-pager"
        />
      )}

      {previewId && (
        <InvoicePreviewModal invoiceId={previewId} onClose={() => setPreviewId(null)} />
      )}
   </div>
  );
};

export default AdminTransactions;
