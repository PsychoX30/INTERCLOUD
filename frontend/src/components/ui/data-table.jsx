import React, { useMemo, useState, useCallback } from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown, Search, Inbox } from "lucide-react";

/**
 * Lightweight, dependency-free table for admin/client views. Handles:
 *  - Column sort (click headers, ascending/descending, tri-state)
 *  - Free-text filter across `searchKeys` columns
 *  - Empty state
 *  - Loading skeleton
 *  - Memoised row rendering
 *
 * Not a replacement for TanStack Table — meant for the many small tables in
 * this app where TanStack's setup cost is disproportionate.
 *
 * Usage:
 *   <DataTable
 *     rows={invoices}
 *     columns={[
 *       { key: "number", label: "Invoice #", sortable: true },
 *       { key: "total",  label: "Total",     sortable: true, align: "right",
 *         render: (v) => formatIDR(v) },
 *       { key: "status", label: "Status",    sortable: true },
 *     ]}
 *     searchKeys={["number", "customer_name"]}
 *     rowKey={(r) => r.id}
 *     onRowClick={(r) => nav(`/invoices/${r.id}`)}
 *     empty={{ title: "No invoices yet", hint: "Create your first invoice." }}
 *     loading={loading}
 *     testid="invoice-table"
 *   />
 */
export const DataTable = React.memo(function DataTable({
  rows,
  columns,
  searchKeys = [],
  rowKey,
  onRowClick,
  empty,
  loading = false,
  searchable = true,
  className = "",
  testid,
}) {
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const [query, setQuery] = useState("");

  const cycleSort = useCallback((key) => {
    setSort((s) => {
      if (s.key !== key) return { key, dir: "asc" };
      if (s.dir === "asc") return { key, dir: "desc" };
      return { key: null, dir: "asc" };
    });
  }, []);

  const filtered = useMemo(() => {
    if (!query.trim() || searchKeys.length === 0) return rows || [];
    const q = query.trim().toLowerCase();
    return (rows || []).filter((r) =>
      searchKeys.some((k) => {
        const v = r?.[k];
        return v != null && String(v).toLowerCase().includes(q);
      })
    );
  }, [rows, query, searchKeys]);

  const sorted = useMemo(() => {
    if (!sort.key) return filtered;
    const cp = [...filtered];
    cp.sort((a, b) => {
      const va = a?.[sort.key];
      const vb = b?.[sort.key];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") return va - vb;
      return String(va).localeCompare(String(vb), undefined, { numeric: true });
    });
    return sort.dir === "asc" ? cp : cp.reverse();
  }, [filtered, sort]);

  const total = rows?.length || 0;
  const shownCount = sorted.length;

  return (
    <div className={"bg-white border border-slate-200 rounded-2xl overflow-hidden " + className}
         data-testid={testid}>
      {(searchable && searchKeys.length > 0) && (
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-3 bg-slate-50/50">
          <div className="relative flex-1 max-w-sm">
            <Search className="h-3.5 w-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={`Search ${searchKeys.length > 1 ? "…" : searchKeys[0]}`}
              className="w-full pl-8 pr-3 py-1.5 rounded-lg text-sm border border-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0a2540]/30 focus:border-[#0a2540]/40"
              data-testid={testid ? `${testid}-search` : undefined}
            />
          </div>
          <div className="text-[11px] uppercase tracking-widest text-slate-400 tabular-nums">
            {shownCount}/{total}
          </div>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/60 text-[10px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              {columns.map((col) => {
                const sortable = col.sortable !== false;
                const active = sort.key === col.key;
                const Icon = !sortable ? null :
                             (active ? (sort.dir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown);
                return (
                  <th key={col.key}
                      className={`px-4 py-3 select-none ${col.align === "right" ? "text-right" : "text-left"} ${sortable ? "cursor-pointer hover:text-[#0a2540]" : ""}`}
                      onClick={sortable ? () => cycleSort(col.key) : undefined}
                      data-testid={testid ? `${testid}-th-${col.key}` : undefined}>
                    <span className="inline-flex items-center gap-1.5">
                      {col.label}
                      {Icon && <Icon className="h-3 w-3 opacity-50" />}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {loading && (
              <>
                {[0, 1, 2, 3].map((i) => (
                  <tr key={`sk-${i}`} className="border-t border-slate-100">
                    {columns.map((c) => (
                      <td key={c.key} className="px-4 py-3">
                        <div className="h-3 rounded bg-slate-100 animate-pulse" style={{ width: `${60 + ((i * 17 + c.key.length * 7) % 30)}%` }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </>
            )}
            {!loading && sorted.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-16 text-center"
                    data-testid={testid ? `${testid}-empty` : undefined}>
                  <div className="flex flex-col items-center gap-2 text-slate-400">
                    <Inbox className="h-8 w-8 opacity-40" />
                    <div className="text-sm font-semibold">{empty?.title || "No data"}</div>
                    {empty?.hint && <div className="text-xs">{empty.hint}</div>}
                  </div>
                </td>
              </tr>
            )}
            {!loading && sorted.map((r, idx) => {
              const key = rowKey ? rowKey(r) : (r?.id ?? idx);
              return (
                <tr key={key}
                    className={`border-t border-slate-100 ${onRowClick ? "cursor-pointer hover:bg-slate-50/60 transition-colors" : ""}`}
                    onClick={onRowClick ? () => onRowClick(r) : undefined}
                    data-testid={testid ? `${testid}-row-${key}` : undefined}>
                  {columns.map((col) => (
                    <td key={col.key}
                        className={`px-4 py-2 ${col.align === "right" ? "text-right tabular-nums" : ""} ${col.mono ? "font-mono text-xs" : ""}`}>
                      {col.render ? col.render(r?.[col.key], r) : r?.[col.key]}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
});

export default DataTable;
