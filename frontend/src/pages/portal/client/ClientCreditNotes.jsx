import React, { useEffect, useState } from "react";
import { api, money, shortDate, docUrl } from "../../../portal/api";
import { PageHeader, Loading, StatusBadge, EmptyState } from "../ui";
import { FileDown, Download, BadgePercent } from "lucide-react";

const ClientCreditNotes = () => {
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api.get("/client/credit-notes").then((r) => setRows(r.data));
  }, []);

  if (!rows) return <Loading />;

  const applied = rows.filter((r) => r.status === "applied").reduce((a, b) => a + b.amount, 0);

  return (
    <div data-testid="client-credit-notes-page">
      <PageHeader title="Credit Notes" subtitle="Kredit dan refund yang diterbitkan untuk akun Anda." />
      {rows.length > 0 && (
        <div className="mb-4 inline-flex items-center gap-2 rounded-2xl bg-emerald-50 border border-emerald-200 px-4 py-3" data-testid="client-cn-total-applied">
          <BadgePercent className="h-5 w-5 text-emerald-600" />
          <span className="text-sm text-emerald-800">Total kredit diterapkan: <span className="font-extrabold">{money(applied)}</span></span>
        </div>
      )}
      {rows.length === 0 && <EmptyState title="Belum ada credit note" subtitle="Credit note atau refund dari tim kami akan muncul di sini." />}
      {rows.length > 0 && (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm" data-testid="client-credit-notes-table">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Credit Note</th>
                <th className="px-4 py-3 text-left hidden sm:table-cell">Tanggal</th>
                <th className="px-4 py-3 text-left">Invoice terkait</th>
                <th className="px-4 py-3 text-left hidden md:table-cell">Alasan</th>
                <th className="px-4 py-3 text-right">Jumlah</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Dokumen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((cn) => (
                <tr key={cn.id} className="border-t border-slate-100 hover:bg-slate-50/50" data-testid={`client-cn-row-${cn.number}`}>
                  <td className="px-4 py-3 font-mono text-[#0a2350] font-bold">{cn.number}</td>
                  <td className="px-4 py-3 hidden sm:table-cell text-slate-600">{shortDate(cn.created_at)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{cn.invoice_number || "-"}</td>
                  <td className="px-4 py-3 hidden md:table-cell text-slate-600">{cn.reason || "-"}</td>
                  <td className="px-4 py-3 text-right font-extrabold text-[#0a2350]">{money(cn.amount)}</td>
                  <td className="px-4 py-3"><StatusBadge status={cn.status} /></td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <a href={docUrl("credit-note", cn.id)} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120] mr-3" title="Preview" data-testid={`client-cn-preview-${cn.number}`}>
                      <FileDown className="h-4 w-4 inline" />
                    </a>
                    <a href={docUrl("credit-note", cn.id, "pdf")} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-[#f5b120]" title="Download PDF" data-testid={`client-cn-download-${cn.number}`}>
                      <Download className="h-4 w-4 inline" />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

export default ClientCreditNotes;
