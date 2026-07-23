import React, { useEffect, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { docUrl } from "../../../portal/api";
import { PageHeader, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Trash2, FileDown, Download } from "lucide-react";
import { DataTable } from "../../../components/ui/data-table";

const AdminQuotations = () => {
  const [rows, setRows] = useState(null);
  const [modal, setModal] = useState(false);
  const load = () => api.get("/admin/quotations").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  const setStatus = async (id, status) => { await api.put(`/admin/quotations/${id}/status`, { status }); load(); };

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
    { key: "valid_until", label: "Valid until", sortable: true,
      render: (v) => <span className="text-slate-500">{shortDate(v)}</span> },
    { key: "total", label: "Total", sortable: true, align: "right",
      render: (v) => <span className="font-extrabold text-[#0a2350]">{money(v)}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusBadge status={v} /> },
    { key: "_actions", label: "Actions", sortable: false, align: "right",
      render: (_v, q) => (
        <span className="whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          <a href={docUrl("quotation", q.id)} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120] mr-3" title="Preview" data-testid={`qtn-pdf-${q.number}`}>
            <FileDown className="h-4 w-4 inline" />
          </a>
          <a href={docUrl("quotation", q.id, "pdf")} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120] mr-3" title="Download PDF" data-testid={`qtn-download-${q.number}`}>
            <Download className="h-4 w-4 inline" />
          </a>
          <select value={q.status} onChange={(e) => setStatus(q.id, e.target.value)} className="text-xs h-8 rounded border border-slate-300 px-1.5" data-testid={`qtn-status-${q.number}`}>
            <option value="draft">draft</option>
            <option value="sent">sent</option>
            <option value="accepted">accepted</option>
            <option value="rejected">rejected</option>
            <option value="expired">expired</option>
          </select>
        </span>
      ) },
  ];

  return (
    <div>
      <PageHeader
        title="Quotations"
        subtitle="Send tailored quotes to prospects. Accepted quotes can be converted into invoices."
        actions={<button className={btnPrimary} onClick={() => setModal(true)} data-testid="new-qtn-btn"><Plus className="h-4 w-4" /> New Quotation</button>}
      />
      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["number", "user_name", "user_email", "status"]}
        rowKey={(r) => r.id}
        empty={{ title: "No quotations yet", hint: "Send your first quote to a prospect." }}
        testid="admin-quotations-table"
      />
      {modal && <NewQuotation onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
    </div>
  );
};

const NewQuotation = ({ onClose, onDone }) => {
  const [users, setUsers] = useState([]);
  const [userId, setUserId] = useState("");
  const [items, setItems] = useState([{ description: "", qty: 1, unit_price: 0, total: 0 }]);
  const [taxPercent, setTaxPercent] = useState(11);
  const [validUntil, setValidUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.get("/admin/users").then((r) => {
      const cs = r.data.filter((u) => u.role === "client");
      setUsers(cs); if (cs[0]) setUserId(cs[0].id);
    });
    const d = new Date(); d.setDate(d.getDate() + 30);
    setValidUntil(d.toISOString().slice(0, 10));
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
    e.preventDefault(); setBusy(true); setErr("");
    try {
      await api.post("/admin/quotations", {
        user_id: userId,
        items: items.filter((i) => i.description).map((i) => ({ ...i, total: i.qty * i.unit_price })),
        tax_percent: Number(taxPercent),
        valid_until: validUntil,
      });
      onDone();
    } catch (er) { setErr(er?.response?.data?.detail || "Failed"); } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="new-qtn-form">
        <h3 className="text-xl font-extrabold text-[#0a2350]">New quotation</h3>
        {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="col-span-2">
            <div className={labelClass}>Client</div>
            <select value={userId} onChange={(e) => setUserId(e.target.value)} className={inputClass}>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name} · {u.email}</option>)}
            </select>
          </label>
          <label><div className={labelClass}>Tax %</div><input type="number" value={taxPercent} onChange={(e) => setTaxPercent(e.target.value)} className={inputClass} /></label>
          <label><div className={labelClass}>Valid until</div><input type="date" value={validUntil} onChange={(e) => setValidUntil(e.target.value)} className={inputClass} required /></label>
        </div>
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <div className={labelClass}>Line items</div>
            <button type="button" className="text-xs text-[#f5b120] font-bold" onClick={() => setItems([...items, { description: "", qty: 1, unit_price: 0, total: 0 }])}>+ Add line</button>
          </div>
          {items.map((it, i) => (
            <div key={i} className="grid grid-cols-12 gap-2 mb-2">
              <input placeholder="Description" value={it.description} onChange={(e) => setItem(i, "description", e.target.value)} className={`${inputClass} col-span-6`} required />
              <input type="number" min="1" value={it.qty} onChange={(e) => setItem(i, "qty", e.target.value)} className={`${inputClass} col-span-2`} />
              <input type="number" value={it.unit_price} onChange={(e) => setItem(i, "unit_price", e.target.value)} className={`${inputClass} col-span-3`} />
              <button type="button" onClick={() => setItems(items.filter((_, x) => x !== i))} className="col-span-1 text-slate-500 hover:text-red-600" disabled={items.length === 1}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
        <div className="mt-5 border-t border-slate-100 pt-4 text-right space-y-1 text-sm">
          <div className="text-slate-500">Subtotal: <span className="font-semibold text-[#0a2350]">{money(subtotal)}</span></div>
          <div className="text-slate-500">Tax ({taxPercent}%): <span className="font-semibold text-[#0a2350]">{money(tax)}</span></div>
          <div className="text-lg font-extrabold text-[#0a2350]">Total: {money(total)}</div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary}>Create quotation</button>
        </div>
      </form>
    </div>
  );
};

export default AdminQuotations;
