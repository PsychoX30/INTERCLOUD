import React, { useEffect, useState } from "react";
import { Save, Loader2, MessageSquare, ExternalLink, AlertCircle } from "lucide-react";
import { api } from "../../../portal/api";

const DEFAULTS = {
  enabled: false,
  widget_id: "",
  api_base: "https://chat.intercloud-digital.com",
};

const AdminChat = () => {
  const [cfg, setCfg] = useState(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    let alive = true;
    api
      .get("/chat/config")
      .then(({ data }) => {
        if (!alive) return;
        setCfg({ ...DEFAULTS, ...(data || {}) });
      })
      .catch(() => {
        if (alive) setMsg({ kind: "error", text: "Gagal memuat konfigurasi chat" });
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const body = {
        enabled: !!cfg.enabled,
        widget_id: (cfg.widget_id || "").trim(),
        api_base: (cfg.api_base || "").trim() || DEFAULTS.api_base,
      };
      const { data } = await api.post("/admin/chat/config", body);
      setCfg({ ...DEFAULTS, ...(data || {}) });
      setMsg({
        kind: "ok",
        text: `Tersimpan - widget live chat sekarang ${data?.enabled ? "AKTIF" : "NONAKTIF"} di halaman publik.`,
      });
    } catch (e) {
      setMsg({ kind: "error", text: e?.response?.data?.detail || e.message || "Gagal menyimpan" });
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-slate-400">Memuat…</div>;
  }

  const chatUrl = (cfg.api_base || "").replace(/\/+$/, "");

  return (
    <div className="p-6 max-w-2xl" data-testid="admin-chat-page">
      <div className="flex items-center gap-3 mb-2">
        <div className="h-10 w-10 rounded-xl bg-[#0a2350] flex items-center justify-center">
          <MessageSquare className="h-5 w-5 text-[#f5b120]" strokeWidth={2} />
        </div>
        <div>
          <h1 className="text-lg md:text-xl font-bold text-[#0a2350]">Live Chat</h1>
          <p className="text-xs text-slate-500">Widget Chatwoot untuk landing page & portal klien.</p>
        </div>
      </div>

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6 space-y-5">
        <label className="flex items-start gap-3 cursor-pointer select-none" data-testid="chat-enabled-toggle">
          <input
            type="checkbox"
            checked={!!cfg.enabled}
            onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
            className="mt-0.5 h-5 w-5 rounded border-slate-300 text-[#f5b120] focus:ring-[#f5b120]"
          />
          <span>
            <span className="block text-sm font-semibold text-[#0a2350]">Aktifkan widget</span>
            <span className="block text-xs text-slate-500 mt-0.5">
              Kalau dimatikan, tombol chat tidak dipasang sama sekali di halaman publik.
            </span>
          </span>
        </label>

        <div>
          <label htmlFor="chat-widget-id" className="block text-sm font-medium text-[#0a2350] mb-1">
            Website Token (Widget ID)
          </label>
          <input
            id="chat-widget-id"
            value={cfg.widget_id}
            onChange={(e) => setCfg({ ...cfg, widget_id: e.target.value })}
            placeholder="mis. aBcD1234efGh5678"
            spellCheck={false}
            data-testid="chat-widget-id"
            className="w-full px-4 py-2.5 rounded-xl border border-slate-300 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none font-mono text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">
            Ambil dari Chatwoot: Settings ▸ Inboxes ▸ Website ▸ Configuration.
          </p>
        </div>

        <div>
          <label htmlFor="chat-api-base" className="block text-sm font-medium text-[#0a2350] mb-1">
            Base URL Chatwoot
          </label>
          <input
            id="chat-api-base"
            value={cfg.api_base}
            onChange={(e) => setCfg({ ...cfg, api_base: e.target.value })}
            placeholder={DEFAULTS.api_base}
            spellCheck={false}
            data-testid="chat-api-base"
            className="w-full px-4 py-2.5 rounded-xl border border-slate-300 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none text-sm"
          />
          {chatUrl && (
            <a
              href={chatUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-[#f5b120]"
            >
              Buka dashboard <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>

        {cfg.enabled && !cfg.widget_id && (
          <div className="flex items-start gap-2 rounded-xl bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">
            <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <span>Widget aktif tapi Website Token kosong - widget tidak akan tampil sampai token diisi.</span>
          </div>
        )}

        {msg && (
          <div
            className={`p-3 rounded-xl text-sm ${
              msg.kind === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
            }`}
            data-testid="chat-msg"
          >
            {msg.text}
          </div>
        )}

        <button
          onClick={save}
          disabled={busy}
          className="px-5 py-2.5 rounded-lg bg-[#0a2350] text-white text-sm font-semibold hover:bg-[#1a355c] disabled:opacity-50 inline-flex items-center gap-2"
          data-testid="chat-save"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          Simpan
        </button>
      </div>
    </div>
  );
};

export default AdminChat;