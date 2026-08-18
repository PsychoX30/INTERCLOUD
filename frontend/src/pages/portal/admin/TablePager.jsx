import React from "react";

/** Shared server-side table pagination. page is zero-based; limit=0 means all. */
export const TablePager = ({
  page,
  total,
  limit,
  onPage,
  onLimit,
  testid = "pager",
}) => {
  const isAll = !limit || limit === 0;
  const pages = isAll ? 1 : Math.max(1, Math.ceil((total || 0) / limit));
  const from = total === 0 ? 0 : isAll ? 1 : page * limit + 1;
  const to = isAll ? (total || 0) : Math.min((page + 1) * limit, total || 0);
  return (
    <div
      className="px-5 py-3 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"
      data-testid={testid}
    >
      <span data-testid={`${testid}-range`}>{from}-{to} dari {total || 0}</span>
      <div className="flex items-center gap-2">
        {onLimit && (
          <label className="flex items-center gap-1">
            Tampilkan
            <select
              value={isAll ? 0 : limit}
              onChange={(e) => onLimit(Number(e.target.value))}
              className="px-1.5 py-1 rounded border border-slate-300 bg-white"
              data-testid={`${testid}-limit`}
            >
              <option value={10}>10</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={0}>Semua</option>
            </select>
          </label>
        )}
        <button type="button" className="px-2.5 py-1 rounded-lg border border-slate-300 font-semibold disabled:opacity-40 hover:border-[#f5b120]" disabled={page <= 0 || isAll} onClick={() => onPage(page - 1)} data-testid={`${testid}-prev`}>Sebelumnya</button>
        <span className="tabular-nums">Halaman {page + 1} / {pages}</span>
        <button type="button" className="px-2.5 py-1 rounded-lg border border-slate-300 font-semibold disabled:opacity-40 hover:border-[#f5b120]" disabled={page >= pages - 1 || isAll} onClick={() => onPage(page + 1)} data-testid={`${testid}-next`}>Berikutnya</button>
      </div>
    </div>
  );
};

export default TablePager;
