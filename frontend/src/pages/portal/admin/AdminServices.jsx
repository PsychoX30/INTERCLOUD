import React, { useEffect, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, StatusBadge } from "../ui";

const AdminServices = () => {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/admin/services").then((r) => setRows(r.data)); }, []);
  if (!rows) return <Loading />;
  return (
    <div>
      <PageHeader title="Active Services" subtitle="Every provisioned instance across your clients." />
      {rows.length === 0 && <EmptyState title="No services" />}
      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Service</th>
              <th className="px-4 py-3 text-left">Category</th>
              <th className="px-4 py-3 text-left">Client</th>
              <th className="px-4 py-3 text-left">Renewal</th>
              <th className="px-4 py-3 text-right">Monthly</th>
              <th className="px-4 py-3 text-left">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id} className="border-t border-slate-100">
                <td className="px-4 py-3">
                  <div className="font-semibold text-[#0a2350]">{s.product_name}</div>
                  <div className="text-xs text-slate-500">{s.name}</div>
                </td>
                <td className="px-4 py-3 uppercase text-xs font-bold text-[#f5b120]">{s.category}</td>
                <td className="px-4 py-3 text-xs">{s.user_id}</td>
                <td className="px-4 py-3 text-slate-500">{shortDate(s.next_renewal)}</td>
                <td className="px-4 py-3 text-right font-semibold">{money(s.price_monthly)}</td>
                <td className="px-4 py-3"><StatusBadge status={s.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default AdminServices;
