import React, { useEffect, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader } from "../ui";
import { DataTable } from "../../../components/ui/data-table";

const STATUS_COLORS = {
  paid: "bg-emerald-100 text-emerald-700",
  unpaid: "bg-amber-100 text-amber-700",
  pending: "bg-slate-100 text-slate-600",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-indigo-100 text-indigo-700",
  cancelled: "bg-slate-100 text-slate-500",
};

const StatusPill = ({ status }) => (
  <span className={`inline-block text-[11px] font-bold uppercase px-2 py-0.5 rounded-full ${STATUS_COLORS[status] || "bg-slate-100 text-slate-600"}`}>
    {status || "-"}
  </span>
);

const AdminTransactions = () => {
  const [rows, setRows] = useState(null);
  const [summary, setSummary] = useState(null);
  const [dateRange, setDateRange] = useState({ start: "", end: "" });

  const load = () => {
    const params = {
      start: dateRange.start ? `${dateRange.start}T00:00:00` : undefined,
      end: dateRange.end ? `${dateRange.end}T23:59:59` : undefined,
    };
    api.get("/admin/transactions", { params }).then((r) => setRows(r.data));
    api.get("/admin/transactions/summary", { params }).then((r) => setSummary(r.data));
  };
  useEffect(() => { load(); }, [dateRange.start, dateRange.end]);

  const columns = [
    { key: "id", label: "ID", sortable: false, mono: true,
      render: (v) => <span className="font-mono text-slate-400 text-xs">{v ? String(v).slice(-8) : "-"}</span> },
    { key: "invoice_number", label: "Invoice #", sortable: true,
      render: (v) => (v ? <span className="font-mono font-bold text-[#0a2350]">{v}</span> : "-") },
    { key: "customer_name", label: "Customer", sortable: true,
      render: (v) => <span className="font-semibold text-[#0a2350]">{v || "-"}</span> },
    { key: "amount", label: "Amount", sortable: true, align: "right",
      render: (v) => <span className="font-extrabold text-[#0a2350]">{money(v)}</span> },
    { key: "method", label: "Method", sortable: true,
      render: (v) => <span className="text-slate-600">{v || "-"}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusPill status={v} /> },
    { key: "paid_at", label: "Paid At", sortable: true,
      render: (v) => <span className="text-slate-500">{shortDate(v)}</span> },
    { key: "verified_at", label: "Verified", sortable: true,
      render: (v) => v ? <span className="text-emerald-600 text-xs">verified</span> : <span className="text-slate-400 text-xs">pending</span> },
    { key: "notes", label: "Notes", sortable: false,
      render: (v) => <span className="text-xs text-slate-500 max-w-[12ch] truncate inline-block" title={v}>{v || "-"}</span> },
  ];

  return (
    <div>
      <PageHeader
        title="Transaction Ledger"
        subtitle="Payment lifecycle view for reconciliation."
      />
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 p-4 bg-[#f8fafc] rounded-lg border border-slate-200">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Paid</div>
            <div className="text-2xl font-extrabold text-[#0a2350]">{money(summary.paid_amount)}</div>
            <div className="text-xs text-slate-500">{summary.paid_count} transactions</div>
          </div>
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">Outstanding</div>
            <div className="text-2xl font-extrabold text-[#ea580c]">{money(summary.outstanding_amount)}</div>
            <div className="text-xs text-slate-500">To collect</div>
          </div>
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">From</div>
            <input type="date" className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm w-full focus:outline-none focus:ring-2 focus:ring-[#0a2540]/30"
              value={dateRange.start} onChange={(e) => setDateRange({ ...dateRange, start: e.target.value })} data-testid="date-range-start" />
          </div>
          <div>
            <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500">To</div>
            <input type="date" className="border border-slate-200 rounded-lg px-2 py-1.5 text-sm w-full focus:outline-none focus:ring-2 focus:ring-[#0a2540]/30"
              value={dateRange.end} onChange={(e) => setDateRange({ ...dateRange, end: e.target.value })} data-testid="date-range-end" />
          </div>
        </div>
      )}
      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["invoice_number", "customer_name", "method", "status", "notes"]}
        rowKey={(r) => r.id}
        empty={{ title: "No transactions yet", hint: "Transactions appear when invoices are paid." }}
        testid="admin-transactions-table"
      />
    </div>
  );
};

export default AdminTransactions;