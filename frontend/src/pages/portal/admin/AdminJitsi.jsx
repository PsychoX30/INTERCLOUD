import React, { useEffect, useState } from "react";
import { Save, Loader2 } from "lucide-react";
import { api } from "../../../portal/api";

export default function AdminJitsi() {
  const [cfg, setCfg] = useState({
    enabled: false,
    domain: "meet.intercloud-digital.com",
    default_room_prefix: "intercloud",
    jwt_secret: "",
  });
  const [secretSet, setSecretSet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    api.get("/jitsi/config").then(({ data }) => {
      // jwt_secret TIDAK pernah dikirim server; hanya flag jwt_secret_set.
      setSecretSet(!!data.jwt_secret_set);
      setCfg((prev) => ({ ...prev, ...data, jwt_secret: "" }));
    }).catch(() => { /* keep defaults */ });
  }, []);

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const { data } = await api.post("/admin/jitsi/config", cfg);
      setSecretSet(!!data.jwt_secret_set);
      setCfg((prev) => ({ ...prev, ...data, jwt_secret: "" }));
      setMsg({ kind: "ok", text: "Jitsi config saved – widget now " + (data.enabled ? "ACTIVE" : "INACTIVE") });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="p-6 max-w-xl mx-auto" data-testid="admin-jitsi-page">
      <h1 className="text-xl font-bold text-[#0a2350] mb-4">Jitsi Meet</h1>
      <p className="text-slate-500 mb-6">
        Isi domain dan prefix ruangan yang akan digunakan. Konfigurasi disimpan di CMS dan bisa di‑ubah kapan saja.
      </p>

      <div className="space-y-4">
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={cfg.enabled}
            onChange={e => setCfg({ ...cfg, enabled: e.target.checked })}
            className="h-5 w-5 rounded border-slate-300 text-[#f5b120] focus:ring-[#f5b120]"
          />
          <span className="text-sm font-medium text-[#0a2350]">Enabled</span>
        </label>

        <div>
          <label className="block text-sm font-medium text-[#0a2350] mb-1">Domain</label>
          <input
            value={cfg.domain}
            onChange={e => setCfg({ ...cfg, domain: e.target.value })}
            placeholder="meet.intercloud-digital.com"
            className="w-full px-4 py-2 rounded-xl border border-slate-300 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[#0a2350] mb-1">Room prefix</label>
          <input
            value={cfg.default_room_prefix}
            onChange={e => setCfg({ ...cfg, default_room_prefix: e.target.value })}
            placeholder="intercloud"
            className="w-full px-4 py-2 rounded-xl border border-slate-300 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[#0a2350] mb-1">JWT secret (optional)</label>
          <input
            value={cfg.jwt_secret}
            onChange={e => setCfg({ ...cfg, jwt_secret: e.target.value })}
            placeholder={secretSet ? "•••••••• (sudah tersimpan)" : "belum ada secret"}
            autoComplete="new-password"
            className="w-full px-4 py-2 rounded-xl border border-slate-300 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none"
          />
          <p className="mt-2 text-slate-500 text-xs">
            Secret tidak pernah dikirim balik oleh server. Biarkan kosong untuk mempertahankan
            secret yang sudah tersimpan; isi untuk menggantinya.
          </p>
        </div>
      </div>

      {msg && (
        <div className={`mt-4 p-3 rounded-lg text-sm ${msg.kind === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
          {msg.text}
        </div>
      )}

      <button
        onClick={save}
        disabled={busy}
        className="mt-6 px-5 py-2 rounded-lg bg-[#0a2350] text-white font-semibold hover:bg-[#1a355c] disabled:opacity-50 inline-flex items-center gap-2"
        data-testid="jitsi-save"
      >
        <Save className="h-4 w-4" /> {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Simpan"}
      </button>
    </div>
  );
}