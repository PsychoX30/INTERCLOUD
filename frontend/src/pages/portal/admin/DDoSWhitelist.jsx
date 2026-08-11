import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { Card, btnSecondary, labelClass } from "../ui";
import { Shield, Plus, Trash2, X, Check, Loader2, Info } from "lucide-react";
import { useAuth } from "../../../portal/AuthContext";

const parsePrefixes = (raw) => {
  if (Array.isArray(raw)) return raw.join("\n");
  return String(raw || "");
};

const parsePrefixesOut = (raw) =>
  String(raw || "")
    .split(/[\s,]+/)
    .map((p) => p.trim())
    .filter(Boolean);

export const DDoSWhitelist = () => {
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const { user } = useAuth() || {};
  const isAdmin = user?.role?.toLowerCase() === "admin";

  const load = () =>
    api
      .get("/admin/noc/ddos-whitelist")
      .then((r) => {
        setData(r.data);
        setDraft(parsePrefixes(r.data?.custom || []));
      })
      .catch(() => setData({ default: [], active: [], custom: [] }));

  useEffect(() => {
    load();
  }, []);

  const add = () => {
    const txt = window.prompt("Tambah prefix CIDR (mis. 10.10.10.0/24 atau 1.2.3.4):");
    if (!txt) return;
    const trimmed = txt.trim();
    if (!trimmed) return;
    setDraft((d) => (d ? `${d}\n${trimmed}` : trimmed));
  };

  const remove = (idx) => {
    setDraft((d) =>
      d
        .split("\n")
        .filter((_, i) => i !== idx)
        .join("\n")
    );
  };

  const save = async () => {
    setBusy(true);
    setErr("");
    try {
      const prefixes = parsePrefixesOut(draft);
      await api.put("/admin/noc/ddos-whitelist", { prefixes });
      await load();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal menyimpan whitelist");
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm("Kembalikan ke default? Custom whitelist akan dihapus.")) return;
    setBusy(true);
    try {
      await api.put("/admin/noc/ddos-whitelist", { prefixes: [] });
      await load();
    } finally {
      setBusy(false);
    }
  };

  const lines = (draft || "").split("\n").filter((l) => l.trim());
  const customCount = (data?.custom || []).length;
  const activeCount = (data?.active || []).length;

  return (
    <Card className="overflow-hidden mb-6" data-testid="ddos-whitelist">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-bold uppercase tracking-widest text-slate-600 flex items-center gap-2">
            <Shield className="h-3.5 w-3.5 text-emerald-600" /> Whitelist Mitigasi DDoS
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            IP/CIDR di whitelist tidak akan pernah di-blackhole oleh auto-mitigasi maupun tombol manual.
            Default mencakup gateway internal (157.20.32.1, .254), loopback, RFC 1918, multicast.
            Admin dapat menambah/menghapus untuk menyesuaikan dengan topologi jaringan.
          </div>
        </div>
      </div>

      {isAdmin && (
        <div className="px-5 py-4 bg-emerald-50/50 border-b border-emerald-200" data-testid="ddos-whitelist-form">
          {err && (
            <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>
          )}
          <div className="grid lg:grid-cols-2 gap-4">
            <div>
              <div className={labelClass}>Custom whitelist (satu CIDR per baris)</div>
              <textarea
                className="w-full h-40 px-3 py-2 border border-slate-300 rounded-lg font-mono text-xs"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={"10.10.10.0/24\n192.168.50.5\n203.0.113.0/24"}
                data-testid="ddos-whitelist-textarea"
              />
              <button
                className="mt-2 text-xs text-slate-600 hover:text-[#0a2350] flex items-center gap-1"
                onClick={add}
                data-testid="ddos-whitelist-add"
              >
                <Plus className="h-3.5 w-3.5" /> Tambah prefix via prompt
              </button>
            </div>
            <div>
              <div className={labelClass}>Preview aktif (setelah save)</div>
              <div className="h-40 px-3 py-2 border border-slate-200 rounded-lg bg-slate-50 overflow-y-auto font-mono text-xs">
                {lines.length === 0 && (
                  <span className="text-slate-400">— kosong (akan pakai default) —</span>
                )}
                {lines.map((l, i) => (
                  <div key={i} className="flex items-center gap-2 py-0.5" data-testid={`ddos-whitelist-line-${i}`}>
                    <span className="flex-1">{l}</span>
                    <button
                      className="text-slate-400 hover:text-red-600"
                      onClick={() => remove(i)}
                      data-testid={`ddos-whitelist-remove-${i}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
                {lines.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-slate-200 text-slate-500">— fallback ke default —</div>
                )}
                {(data?.default || []).map((p) => (
                  <div key={`d-${p}`} className="text-slate-500 py-0.5">
                    {p} <span className="text-[10px]">(default)</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-3 flex gap-2">
            <button className={btnSecondary} onClick={save} disabled={busy} data-testid="ddos-whitelist-save">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />} Simpan
            </button>
            <button className={btnSecondary} onClick={reset} disabled={busy} data-testid="ddos-whitelist-reset">
              <X className="h-4 w-4" /> Reset ke default
            </button>
          </div>
        </div>
      )}

      <div
        className="px-5 py-3 text-xs text-slate-600 flex flex-wrap items-center gap-x-4 gap-y-1"
        data-testid="ddos-whitelist-summary"
      >
        <span className="inline-flex items-center gap-1.5">
          <Info className="h-3.5 w-3.5 text-slate-400" />
          Saat ini: <strong>{activeCount}</strong> prefix aktif ({customCount} custom +{" "}
          {Math.max(0, activeCount - customCount)} default)
        </span>
        {data?.updated_at && <span className="text-slate-400">Update terakhir: {data.updated_at}</span>}
      </div>
    </Card>
  );
};

export default DDoSWhitelist;