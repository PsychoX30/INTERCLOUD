import React from "react";

/**
 * Kontrol pagination server-side yang dipakai bersama panel NOC.
 * page = zero-based. total/limit datang dari response {items,total,limit,skip}.
 */
export const TablePager = ({ page, total, limit, onPage, testid = "pager" }) => {
  const pages = Math.max(1, Math.ceil((total || 0) / (limit || 1)));
  const from = total === 0 ? 0 : page * limit + 1;
  const to = Math.min((page + 1) * limit, total || 0);
  return (
    <div
      className="px-5 py-3 border-t border-slate-100 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"
      data-testid={testid}
    >
      <span data-testid={`${testid}-range`}>{from}-{to} dari {total || 0}</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="px-2.5 py-1 rounded-lg border border-slate-300 font-semibold disabled:opacity-40 hover:border-[#f5b120]"
          disabled={page <= 0}
          onClick={() => onPage(page - 1)}
          data-testid={`${testid}-prev`}
        >
          Sebelumnya
        </button>
        <span className="tabular-nums">Halaman {page + 1} / {pages}</span>
        <button
          type="button"
          className="px-2.5 py-1 rounded-lg border border-slate-300 font-semibold disabled:opacity-40 hover:border-[#f5b120]"
          disabled={page >= pages - 1}
          onClick={() => onPage(page + 1)}
          data-testid={`${testid}-next`}
        >
          Berikutnya
        </button>
      </div>
    </div>
  );
};

export default TablePager;
