import React, { useEffect, useState } from "react";
import { api, money, shortDate } from "../../../portal/api";
import { PageHeader, StatusBadge } from "../ui";
import { DataTable } from "../../../components/ui/data-table";

const AdminServices = () => {
  const [rows, setRows] = useState(null);
  const [users, setUsers] = useState({});
  useEffect(() => {
    api.get("/admin/services").then((r) => setRows(r.data));
    // Fetch users so we can render human-readable client names instead of raw IDs.
    api.get("/admin/users").then((r) => {
      const map = {};
      for (const u of r.data) map[u.id] = u;
      setUsers(map);
    }).catch(() => {});
  }, []);

  const columns = [
    { key: "product_name", label: "Service", sortable: true,
      render: (_v, s) => (
        <>
          <div className="font-semibold text-[#0a2350]">{s.product_name}</div>
          <div className="text-xs text-slate-500">{s.name}</div>
        </>
      ) },
    { key: "category", label: "Category", sortable: true,
      render: (v) => <span className="uppercase text-xs font-bold text-[#f5b120]">{v}</span> },
    { key: "user_id", label: "Client", sortable: true,
      render: (v) => {
        const u = users[v];
        return u ? (
          <>
            <div className="font-semibold text-[#0a2350]">{u.name}</div>
            <div className="text-xs text-slate-500">{u.email}</div>
          </>
        ) : <span className="text-xs font-mono text-slate-400">{v}</span>;
      } },
    { key: "next_renewal", label: "Renewal", sortable: true,
      render: (v) => <span className="text-slate-500">{shortDate(v)}</span> },
    { key: "price_monthly", label: "Monthly", sortable: true, align: "right",
      render: (v) => <span className="font-semibold">{money(v)}</span> },
    { key: "status", label: "Status", sortable: true,
      render: (v) => <StatusBadge status={v} /> },
  ];

  return (
    <div>
      <PageHeader title="Active Services" subtitle="Every provisioned instance across your clients." />
      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["product_name", "name", "category", "status"]}
        rowKey={(r) => r.id}
        empty={{ title: "No services yet", hint: "Provisioned services will appear here once orders are verified." }}
        testid="admin-services-table"
      />
    </div>
  );
};

export default AdminServices;
