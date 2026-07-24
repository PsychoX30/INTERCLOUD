import React, { useMemo, useState } from "react";
import { PageHeader, Card, inputClass, labelClass, btnPrimary } from "../ui";
import { Copy, CheckCircle2, Link2 } from "lucide-react";
import { toast } from "sonner";

const FIELDS = [
  { key: "utm_source",   label: "Source *",   placeholder: "instagram, google, newsletter", hint: "Where the traffic comes from" },
  { key: "utm_medium",   label: "Medium *",   placeholder: "social, cpc, email",            hint: "Marketing channel type" },
  { key: "utm_campaign", label: "Campaign *", placeholder: "promo-colo-q3",                 hint: "Campaign name (kebab-case)" },
  { key: "utm_term",     label: "Term",       placeholder: "colocation jakarta",            hint: "Paid keyword (optional)" },
  { key: "utm_content",  label: "Content",    placeholder: "banner-a",                      hint: "A/B variant (optional)" },
];

const AdminUTMBuilder = () => {
  const [base, setBase] = useState("https://intercloud-digital.com/");
  const [p, setP] = useState({ utm_source: "", utm_medium: "", utm_campaign: "", utm_term: "", utm_content: "" });
  const [copied, setCopied] = useState(false);

  const result = useMemo(() => {
    let url;
    try { url = new URL(base); } catch { return ""; }
    FIELDS.forEach(({ key }) => {
      const v = (p[key] || "").trim();
      if (v) url.searchParams.set(key, v);
    });
    return url.toString();
  }, [base, p]);

  const valid = result && p.utm_source.trim() && p.utm_medium.trim() && p.utm_campaign.trim();

  const copy = async () => {
    if (!valid) return;
    await navigator.clipboard.writeText(result);
    setCopied(true);
    toast.success("Tagged URL copied to clipboard");
    setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div data-testid="utm-builder-page">
      <PageHeader
        title="UTM Builder"
        subtitle="Generate campaign-tagged URLs for social posts, ads, and newsletters — so analytics can attribute every visit correctly."
      />
      <div className="grid lg:grid-cols-2 gap-4">
        <Card className="p-5">
          <label className="block mb-4"><div className={labelClass}>Destination URL *</div>
            <input value={base} onChange={(e) => setBase(e.target.value)} className={inputClass}
                   placeholder="https://intercloud-digital.com/articles/…" data-testid="utm-base-input" />
            {!result && base && <div className="text-xs text-red-600 mt-1">Enter a valid URL (must start with https://)</div>}
          </label>
          <div className="grid sm:grid-cols-2 gap-3">
            {FIELDS.map((f) => (
              <label key={f.key} className={f.key === "utm_campaign" ? "sm:col-span-2" : ""}>
                <div className={labelClass}>{f.label}</div>
                <input value={p[f.key]} onChange={(e) => setP({ ...p, [f.key]: e.target.value })}
                       className={inputClass} placeholder={f.placeholder} data-testid={`utm-${f.key}-input`} />
                <div className="text-[10px] text-slate-400 mt-0.5">{f.hint}</div>
              </label>
            ))}
          </div>
        </Card>

        <Card className="p-5 flex flex-col">
          <div className={labelClass}>Generated URL</div>
          <div className={`mt-2 flex-1 rounded-xl border p-4 font-mono text-sm break-all ${valid ? "border-emerald-200 bg-emerald-50/50 text-[#0a2350]" : "border-slate-200 bg-slate-50 text-slate-400"}`}
               data-testid="utm-result">
            {valid ? result : "Fill in destination URL + source, medium, and campaign to generate the link."}
          </div>
          <button onClick={copy} disabled={!valid} className={`${btnPrimary} mt-4 justify-center disabled:opacity-40`} data-testid="utm-copy-btn">
            {copied ? <CheckCircle2 className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied!" : "Copy tagged URL"}
          </button>
          <div className="mt-4 rounded-xl bg-slate-50 border border-slate-200 p-3 text-[11px] text-slate-500 leading-relaxed">
            <Link2 className="h-3.5 w-3.5 inline mr-1 text-[#f5b120]" />
            Convention: lowercase kebab-case values, consistent naming per channel
            (e.g. <code className="bg-white px-1 rounded">instagram / social / promo-colo-q3</code>).
            No data is stored — this tool runs entirely in your browser.
          </div>
        </Card>
      </div>
    </div>
  );
};

export default AdminUTMBuilder;
