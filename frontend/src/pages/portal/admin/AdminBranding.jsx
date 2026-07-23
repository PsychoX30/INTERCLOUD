import React, { useEffect, useState, useCallback } from "react";
import { UploadCloud, RotateCcw, Check, ImageOff, Loader2 } from "lucide-react";
import { api } from "../../../portal/api";

const FIELDS = [
  {
    key: "logo_dark",
    label: "Logo — dark on white",
    hint: "Used on invoice/quotation PDFs, email headers footers, and Google search-result cards. Choose a version whose colours read well on a WHITE background.",
    background: "#ffffff",
  },
  {
    key: "logo_light",
    label: "Logo — light on dark",
    hint: "Used in the landing header/footer over the navy hero. Choose a white/light-coloured variant.",
    background: "#0a2350",
  },
  {
    key: "favicon",
    label: "Favicon",
    hint: "The 32×32 icon in the browser tab. Any square PNG will do — the browser scales it down.",
    background: "#f1f5f9",
  },
  {
    key: "email_banner",
    label: "Email banner (optional)",
    hint: "A wide banner shown above the message body in transactional emails. Leave blank to hide the banner.",
    background: "#f1f5f9",
  },
];

const MAX_BYTES = 4 * 1024 * 1024; // 4 MB — matches backend cap.

const fileToDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });

const readableBytes = (n) => {
  if (!n && n !== 0) return "—";
  if (n > 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n > 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
};

const AdminBranding = () => {
  const [branding, setBranding] = useState(null);
  const [busyKey, setBusyKey] = useState("");
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    const { data } = await api.get("/branding");
    setBranding(data);
  }, []);

  useEffect(() => { load(); }, [load]);

  const onFile = async (key, file) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setMsg({ kind: "error", text: `${file.name} is ${readableBytes(file.size)} — max ${readableBytes(MAX_BYTES)}` });
      return;
    }
    if (!/^image\//.test(file.type)) {
      setMsg({ kind: "error", text: `${file.name} is not an image` });
      return;
    }
    setBusyKey(key); setMsg(null);
    try {
      const dataUrl = await fileToDataUrl(file);
      const { data } = await api.post("/admin/branding", { [key]: dataUrl });
      setBranding(data);
      setMsg({ kind: "ok", text: `Updated ${key} (${readableBytes(file.size)})` });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message });
    } finally {
      setBusyKey("");
    }
  };

  const reset = async (key) => {
    if (!window.confirm(`Reset ${key} to the default?`)) return;
    setBusyKey(key); setMsg(null);
    try {
      const { data } = await api.delete(`/admin/branding/${key}`);
      setBranding(data);
      setMsg({ kind: "ok", text: `${key} reset to default` });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message });
    } finally { setBusyKey(""); }
  };

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto" data-testid="admin-branding-page">
      <div className="mb-8">
        <h1 className="text-2xl md:text-3xl font-bold text-[#0a2350]">Branding</h1>
        <p className="mt-1.5 text-sm text-slate-500 max-w-2xl">
          Upload logo variants, favicon, and email banner without touching code. Changes take effect immediately — new invoices, PDFs, and emails will use the uploaded artwork.
        </p>
      </div>

      {msg && (
        <div className={`mb-6 rounded-xl px-4 py-3 text-sm border ${msg.kind === "error" ? "bg-red-50 border-red-200 text-red-800" : "bg-emerald-50 border-emerald-200 text-emerald-800"}`}
             data-testid="admin-branding-msg">
          {msg.text}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {FIELDS.map((f) => {
          const val = branding?.[f.key] || "";
          const isBusy = busyKey === f.key;
          const isEmpty = !val;
          return (
            <div key={f.key}
                 className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm"
                 data-testid={`admin-branding-card-${f.key}`}>
              <div className="px-5 py-4 border-b border-slate-100 flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-bold text-[#0a2350]">{f.label}</div>
                  <div className="mt-0.5 text-[11px] text-slate-500 leading-relaxed">{f.hint}</div>
                </div>
              </div>

              <div className="p-5" style={{ background: f.background }}>
                <div className="h-40 flex items-center justify-center rounded-lg overflow-hidden"
                     style={{ background: f.background }}>
                  {isEmpty ? (
                    <div className="flex flex-col items-center gap-1 text-slate-400">
                      <ImageOff className="h-8 w-8" />
                      <div className="text-xs">Not set</div>
                    </div>
                  ) : (
                    <img src={val} alt={f.label} className="max-h-full max-w-full object-contain"
                         data-testid={`admin-branding-preview-${f.key}`} />
                  )}
                </div>
              </div>

              <div className="px-5 py-4 flex flex-wrap items-center gap-3 border-t border-slate-100 bg-slate-50/50">
                <label className={`inline-flex items-center gap-2 cursor-pointer text-sm font-semibold px-4 py-2 rounded-lg text-white transition-colors ${isBusy ? "bg-slate-300" : "bg-[#0a2350] hover:bg-[#1a355c]"}`}
                       data-testid={`admin-branding-upload-${f.key}`}>
                  {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UploadCloud className="h-4 w-4" />}
                  {isBusy ? "Uploading…" : "Upload"}
                  <input type="file" accept="image/*" hidden disabled={isBusy}
                         onChange={(e) => onFile(f.key, e.target.files?.[0])} />
                </label>
                <button type="button" onClick={() => reset(f.key)} disabled={isBusy}
                        className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-red-600 transition-colors disabled:opacity-50"
                        data-testid={`admin-branding-reset-${f.key}`}>
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset to default
                </button>
                {!isEmpty && !isBusy && (
                  <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-emerald-700">
                    <Check className="h-3.5 w-3.5" /> Live
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50/40 p-5 text-sm text-slate-600">
        <div className="font-semibold text-[#0a2350] mb-1.5">Where these are used</div>
        <ul className="list-disc pl-5 space-y-1 text-[13px]">
          <li><b>logo_dark</b> — Invoice / Quotation PDF header, all transactional email headers, and the JSON-LD publisher logo picked up by Google search results.</li>
          <li><b>logo_light</b> — Landing page header + footer (dark navy background).</li>
          <li><b>favicon</b> — Reserved for a future favicon-swap; currently uploaded to storage only. Bake into <span className="font-mono">public/index.html</span> or wait for the runtime favicon injector.</li>
          <li><b>email_banner</b> — Optional wide banner rendered inside the email body wrapper. Empty means no banner.</li>
        </ul>
      </div>
    </div>
  );
};

export default AdminBranding;
