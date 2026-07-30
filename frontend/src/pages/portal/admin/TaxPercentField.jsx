import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { inputClass, labelClass } from "../ui";
import { RotateCcw } from "lucide-react";

export const TaxPercentField = ({ value, onChange, testid = "tax-percent-field" }) => {
  const [defaultTax, setDefaultTax] = useState(null);

  useEffect(() => {
    api.get("/admin/billing/settings").then((r) => {
      const dv = Number(r.data?.default_tax_percent);
      if (!Number.isNaN(dv)) { setDefaultTax(dv); onChange(dv); }
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const overridden = defaultTax != null && Number(value) !== defaultTax;

  return (
    <label className="block">
      <div className={`${labelClass} flex items-center justify-between`}>
        <span>PPN %</span>
        {overridden && (
          <button type="button" onClick={() => onChange(defaultTax)}
            className="inline-flex items-center gap-1 text-[10px] font-bold text-[#f5b120] hover:underline"
            title={`Kembalikan ke default ${defaultTax}%`} data-testid={`${testid}-reset`}>
            <RotateCcw className="h-3 w-3" /> Default {defaultTax}%
          </button>
        )}
      </div>
      <input type="number" min="0" step="0.1" value={value}
        onChange={(e) => onChange(e.target.value)} className={inputClass} data-testid={testid} />
      <div className="mt-1 text-[11px] text-slate-400">
        {defaultTax != null
          ? `Default global ${defaultTax}%. Boleh diubah per dokumen, isi 0 untuk bebas pajak.`
          : "Boleh diubah per dokumen, isi 0 untuk bebas pajak."}
      </div>
    </label>
  );
};
