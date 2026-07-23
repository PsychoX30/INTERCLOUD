import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Mail, MailPlus, Send, Star, StarOff, RefreshCw, Loader2, AlertTriangle, Settings, Save, X as XIcon } from "lucide-react";

const AdminMail = () => {
  const [rows, setRows] = useState(null);         // list OR { not_setup: true, message }
  const [selected, setSelected] = useState(null);
  const [showCompose, setShowCompose] = useState(false);
  const [showSetup, setShowSetup] = useState(false);

  const load = async () => {
    try {
      const { data } = await api.get("/admin/mail/inbox");
      setRows(data);
    } catch (e) {
      setRows({ not_setup: true, reason: "error", message: e?.response?.data?.detail || e.message });
    }
  };
  useEffect(() => { load(); }, []);

  const open = async (m) => {
    try {
      const { data } = await api.get(`/admin/mail/messages/${m.id}`);
      setSelected(data);
      load();
    } catch (e) {
      setSelected({ ...m, body: m.preview || "(Failed to load message body — check IMAP integration or refresh)" });
    }
  };

  const notSetup = rows && !Array.isArray(rows) && rows.not_setup;
  const list = Array.isArray(rows) ? rows : [];

  return (
    <div>
      <PageHeader
        title="Webmail"
        subtitle="Inbox pribadi Anda — setiap staff punya credential cPanel IMAP/SMTP sendiri."
        actions={
          <div className="flex gap-2">
            <button className={btnSecondary} onClick={() => setShowSetup(true)} data-testid="mail-setup-btn">
              <Settings className="h-4 w-4" /> Setup Email
            </button>
            <button className={btnPrimary} onClick={() => setShowCompose(true)} data-testid="mail-compose-btn">
              <MailPlus className="h-4 w-4" /> Compose
            </button>
          </div>
        }
      />

      {rows === null && (
        <div className="text-center text-slate-500 py-16 flex items-center justify-center gap-2">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading inbox…
        </div>
      )}

      {notSetup && (
        <div className="rounded-2xl border-2 border-amber-300 bg-amber-50/50 p-8 text-center" data-testid="mail-not-setup-card">
          <div className="mx-auto h-14 w-14 rounded-2xl bg-amber-500/20 flex items-center justify-center mb-4">
            <AlertTriangle className="h-7 w-7 text-amber-700" />
          </div>
          <div className="text-xl font-bold text-amber-900 mb-2">Belum di-setup</div>
          <div className="text-sm text-amber-800 max-w-md mx-auto mb-5">{rows.message}</div>
          <button className={btnPrimary} onClick={() => setShowSetup(true)} data-testid="mail-configure-btn">
            <Settings className="h-4 w-4" /> Klik untuk atur
          </button>
        </div>
      )}

      {Array.isArray(rows) && list.length === 0 && (
        <div className="text-center text-slate-500 py-16">Inbox kosong.</div>
      )}

      {list.length > 0 && (
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 md:col-span-5 rounded-2xl bg-white border border-slate-200 max-h-[70vh] overflow-y-auto" data-testid="mail-list">
            {list.map((m) => (
              <button key={m.id}
                onClick={() => open(m)}
                data-testid={`mail-${m.id}`}
                className={`w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-slate-50 ${
                  selected?.id === m.id ? "bg-slate-100" : ""
                }`}>
                <div className="flex justify-between items-baseline">
                  <div className={`text-sm truncate ${m.unread ? "font-bold text-[#0a2350]" : "text-slate-700"}`}>{m.from_name || m.from_email}</div>
                  <div className="text-[10px] text-slate-400 whitespace-nowrap ml-2">{new Date(m.received_at).toLocaleDateString()}</div>
                </div>
                <div className={`text-sm truncate ${m.unread ? "font-semibold" : ""}`}>{m.subject}</div>
                <div className="text-xs text-slate-500 truncate">{m.preview}</div>
              </button>
            ))}
          </div>
          <div className="col-span-12 md:col-span-7 rounded-2xl bg-white border border-slate-200 p-5 min-h-[70vh]" data-testid="mail-detail">
            {selected ? (
              <>
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <div className="text-xs text-slate-500">From: <span className="font-mono">{selected.from_email}</span></div>
                    <div className="text-lg font-bold text-[#0a2350]">{selected.subject}</div>
                    <div className="text-[11px] text-slate-400">{selected.received_at && new Date(selected.received_at).toLocaleString()}</div>
                  </div>
                </div>
                <div className="whitespace-pre-wrap text-sm text-slate-700 leading-relaxed">{selected.body || "(no body)"}</div>
              </>
            ) : (
              <div className="text-slate-400 text-sm text-center py-20">Pilih pesan untuk melihat isi</div>
            )}
          </div>
        </div>
      )}

      {showSetup && <SetupEmailModal onClose={() => setShowSetup(false)} onDone={() => { setShowSetup(false); load(); }} />}
      {showCompose && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setShowCompose(false)}>
          <div className="w-full max-w-lg bg-white rounded-3xl p-6" onClick={(e) => e.stopPropagation()}>
            <div className="text-lg font-bold text-[#0a2350] mb-2">Compose</div>
            <div className="text-sm text-slate-500">Compose fitur akan dihubungkan ke SMTP Anda setelah setup email. Untuk sementara gunakan client email eksternal (Outlook/Roundcube).</div>
            <div className="text-right mt-4"><button className={btnSecondary} onClick={() => setShowCompose(false)}>Tutup</button></div>
          </div>
        </div>
      )}
    </div>
  );
};

const SetupEmailModal = ({ onClose, onDone }) => {
  const [form, setForm] = useState({
    from_name: "", from_email: "",
    imap: { host: "", port: 993, username: "", password: "", use_ssl: true },
    smtp: { host: "", port: 465, username: "", password: "", use_ssl: true },
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.get("/settings/email").then((r) => {
      const d = r.data || {};
      if (d.configured) {
        setForm((prev) => ({
          from_name: d.from_name || "",
          from_email: d.from_email || "",
          imap: { host: d.imap?.credentials?.host || "", port: d.imap?.credentials?.port || 993, username: d.imap?.credentials?.username || "", password: "••••••••", use_ssl: d.imap?.options?.use_ssl !== false },
          smtp: { host: d.smtp?.credentials?.host || "", port: d.smtp?.credentials?.port || 465, username: d.smtp?.credentials?.username || "", password: "••••••••", use_ssl: d.smtp?.options?.use_ssl !== false },
        }));
      }
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, []);

  const save = async () => {
    setBusy(true); setErr("");
    try {
      await api.post("/settings/email", form);
      onDone();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const setField = (kind, key, value) => setForm({ ...form, [kind]: { ...form[kind], [key]: value } });

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="mail-setup-modal">
        <div className="flex justify-between items-start mb-4">
          <div>
            <div className="text-xl font-extrabold text-[#0a2350]">Setup Email Pribadi (cPanel)</div>
            <div className="text-sm text-slate-500">Kredensial ini hanya untuk akun Anda — admin lain tidak bisa melihatnya.</div>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-800"><XIcon className="h-5 w-5" /></button>
        </div>
        {err && <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
        {!loaded ? <div className="text-slate-500">Loading…</div> : (
          <>
            <div className="grid grid-cols-2 gap-3 mb-4">
              <label><div className={labelClass}>Display Name</div><input className={inputClass} value={form.from_name} onChange={(e) => setForm({ ...form, from_name: e.target.value })} placeholder="e.g. Anang Support" data-testid="mail-setup-from-name" /></label>
              <label><div className={labelClass}>From Address</div><input className={inputClass} value={form.from_email} onChange={(e) => setForm({ ...form, from_email: e.target.value })} placeholder="anang@intercloud-digital.com" data-testid="mail-setup-from-email" /></label>
            </div>
            <div className="border-t border-slate-100 pt-3 mb-3">
              <div className="text-sm font-bold text-[#0a2350] mb-2">IMAP (incoming)</div>
              <div className="grid grid-cols-3 gap-3">
                <label className="col-span-2"><div className={labelClass}>Host</div><input className={inputClass} value={form.imap.host} onChange={(e) => setField("imap", "host", e.target.value)} placeholder="mail.intercloud-digital.com" data-testid="mail-setup-imap-host" /></label>
                <label><div className={labelClass}>Port</div><input type="number" className={inputClass} value={form.imap.port} onChange={(e) => setField("imap", "port", e.target.value)} /></label>
                <label className="col-span-2"><div className={labelClass}>Username</div><input className={inputClass} value={form.imap.username} onChange={(e) => setField("imap", "username", e.target.value)} placeholder="anang@intercloud-digital.com" data-testid="mail-setup-imap-user" /></label>
                <label><div className={labelClass}>Password</div><input type="password" className={inputClass} value={form.imap.password} onChange={(e) => setField("imap", "password", e.target.value)} data-testid="mail-setup-imap-pass" /></label>
              </div>
            </div>
            <div className="border-t border-slate-100 pt-3 mb-4">
              <div className="text-sm font-bold text-[#0a2350] mb-2">SMTP (outgoing)</div>
              <div className="grid grid-cols-3 gap-3">
                <label className="col-span-2"><div className={labelClass}>Host</div><input className={inputClass} value={form.smtp.host} onChange={(e) => setField("smtp", "host", e.target.value)} placeholder="mail.intercloud-digital.com" data-testid="mail-setup-smtp-host" /></label>
                <label><div className={labelClass}>Port</div><input type="number" className={inputClass} value={form.smtp.port} onChange={(e) => setField("smtp", "port", e.target.value)} /></label>
                <label className="col-span-2"><div className={labelClass}>Username</div><input className={inputClass} value={form.smtp.username} onChange={(e) => setField("smtp", "username", e.target.value)} data-testid="mail-setup-smtp-user" /></label>
                <label><div className={labelClass}>Password</div><input type="password" className={inputClass} value={form.smtp.password} onChange={(e) => setField("smtp", "password", e.target.value)} data-testid="mail-setup-smtp-pass" /></label>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button className={btnSecondary} onClick={onClose}>Batal</button>
              <button className={btnPrimary} onClick={save} disabled={busy} data-testid="mail-setup-save">
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Simpan
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default AdminMail;
