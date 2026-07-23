import React, { useEffect, useState } from "react";
import { api, money, shortDate, docUrl } from "../../../portal/api";
import { PageHeader, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Trash2, CheckCircle2, FileDown, Download } from "lucide-react";
import { DataTable } from "../../../components/ui/data-table";

const AdminInvoices = () => {
  const [rows, setRows] = useState(null);
  const [modal, setModal] = useState(false);
  const load = () => api.get("/admin/invoices").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  const markPaid = async (id) => { await api.put(`/admin/invoices/${id}/status`, { status: "paid", payment_method: "bank_transfer" }); load(); };
  const cancel = async (id) => { if (window.confirm("Cancel invoice?")) { await api.put(`/admin/invoices/${id}/status`, { status: "cancelled" }); load(); } };

  const columns = [
    { key: "number", label: "#", sortable: true, mono: true,
      render: (v) => <span className="font-mono font-bold text-[#0a2350]">{v}</span> },
    { key: "user_name", label: "Client", sortable: true,
      render: (_v, r) => (
        <>
          <div className="font-semibold text-[#0a2350]">{r.user_name}</div>
          <div className="text-xs text-slate-500">{r.user_email}</div>
        </>
      ) },
    { key: "created_at", label: "Issued", sortable: true,
      render: (v) => <span className="text-slate-500">{shortDate(v)}</span> },
    { key: "due_date", label: "Due", sortable: true,
      render: (v) => <span className="text-slate-500">{shortDate(v)}</span> },
    { key: "total", label: "Total", sortable: true, align: "right",
      render: (v) => <span className="font-extrabold text-[#0a2350]">{money(v)}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusBadge status={v} /> },
    { key: "_actions", label: "Actions", sortable: false, align: "right",
      render: (_v, inv) => (
        <span className="whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          <a href={docUrl("invoice", inv.id)} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120]" title="Preview" data-testid={`inv-pdf-${inv.number}`}>
            <FileDown className="h-4 w-4 inline" />
          </a>
          <a href={docUrl("invoice", inv.id, "pdf")} target="_blank" rel="noreferrer" className="ml-3 text-slate-600 hover:text-[#f5b120]" title="Download PDF" data-testid={`inv-download-${inv.number}`}>
            <Download className="h-4 w-4 inline" />
          </a>
          {(inv.status === "unpaid" || inv.status === "overdue") && (
            <button className="ml-3 text-emerald-600 hover:text-emerald-800" onClick={() => markPaid(inv.id)} title="Mark Paid" data-testid={`inv-pay-${inv.number}`}>
              <CheckCircle2 className="h-4 w-4 inline" />
            </button>
          )}
          {inv.status !== "cancelled" && (
            <button className="ml-3 text-slate-500 hover:text-red-600" onClick={() => cancel(inv.id)} title="Cancel">
              <Trash2 className="h-4 w-4 inline" />
            </button>
          )}
        </span>
      ) },
  ];

  return (
    <div>
      <PageHeader
        title="Invoices"
        subtitle="Create invoices, mark paid, and track overdue accounts."
        actions={<button className={btnPrimary} onClick={() => setModal(true)} data-testid="new-invoice-btn"><Plus className="h-4 w-4" /> New Invoice</button>}
      />
      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["number", "user_name", "user_email", "status"]}
        rowKey={(r) => r.id}
        empty={{ title: "No invoices yet", hint: "Create your first invoice." }}
        testid="admin-invoices-table"
      />
      {modal && <NewInvoice onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
    </div>
  );
};

const NewInvoice = ({ onClose, onDone }) => {
  const [users, setUsers] = useState([]);
  const [userId, setUserId] = useState("");
  const [items, setItems] = useState([{ description: "", qty: 1, unit_price: 0, total: 0 }]);
  const [taxPercent, setTaxPercent] = useState(11);
  const [dueDate, setDueDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/admin/users").then((r) => {
      const clients = r.data.filter((u) => u.role === "client");
      setUsers(clients);
      if (clients[0]) setUserId(clients[0].id);
    });
    const d = new Date(); d.setDate(d.getDate() + 14);
    setDueDate(d.toISOString().slice(0, 10));
  }, []);

  const setItem = (i, key, val) => {
    const copy = [...items];
    copy[i][key] = key === "description" ? val : Number(val) || 0;
    copy[i].total = copy[i].qty * copy[i].unit_price;
    setItems(copy);
  };

  const subtotal = items.reduce((a, b) => a + b.total, 0);
  const tax = subtotal * taxPercent / 100;
  const total = subtotal + tax;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await api.post("/admin/invoices", {
        user_id: userId,
        items: items.filter((i) => i.description).map((i) => ({ ...i, total: i.qty * i.unit_price })),
        tax_percent: Number(taxPercent),
        due_date: dueDate,
      });
      onDone();
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="new-invoice-form">
        <h3 className="text-xl font-extrabold text-[#0a2350]">New invoice</h3>
        {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="col-span-2">
            <div className={labelClass}>Client</div>
            <select value={userId} onChange={(e) => setUserId(e.target.value)} className={inputClass} data-testid="inv-client">
              {users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.email}</option>)}
            </select>
          </label>
          <label>
            <div className={labelClass}>Tax %</div>
            <input type="number" value={taxPercent} onChange={(e) => setTaxPercent(e.target.value)} className={inputClass} />
          </label>
          <label>
            <div className={labelClass}>Due date</div>
            <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className={inputClass} required data-testid="inv-due" />
          </label>
        </div>

        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <div className={labelClass}>Line items</div>
            <button type="button" className="text-xs text-[#f5b120] font-bold" onClick={() => setItems([...items, { description: "", qty: 1, unit_price: 0, total: 0 }])}>+ Add line</button>
          </div>
          <div className="space-y-2">
            {items.map((it, i) => (
              <div key={i} className="grid grid-cols-12 gap-2">
                <input placeholder="Description" value={it.description} onChange={(e) => setItem(i, "description", e.target.value)} className={`${inputClass} col-span-6`} required data-testid={`inv-desc-${i}`} />
                <input type="number" min="1" placeholder="Qty" value={it.qty} onChange={(e) => setItem(i, "qty", e.target.value)} className={`${inputClass} col-span-2`} />
                <input type="number" placeholder="Unit price" value={it.unit_price} onChange={(e) => setItem(i, "unit_price", e.target.value)} className={`${inputClass} col-span-3`} data-testid={`inv-price-${i}`} />
                <button type="button" onClick={() => setItems(items.filter((_, x) => x !== i))} className="col-span-1 text-slate-500 hover:text-red-600" disabled={items.length === 1}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-5 border-t border-slate-100 pt-4 text-right space-y-1 text-sm">
          <div className="text-slate-500">Subtotal: <span className="font-semibold text-[#0a2350]">{money(subtotal)}</span></div>
          <div className="text-slate-500">Tax ({taxPercent}%): <span className="font-semibold text-[#0a2350]">{money(tax)}</span></div>
          <div className="text-lg font-extrabold text-[#0a2350]">Total: {money(total)}</div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary} data-testid="inv-submit">Create invoice</button>
        </div>
      </form>
    </div>
  );
};

export default AdminInvoices;
