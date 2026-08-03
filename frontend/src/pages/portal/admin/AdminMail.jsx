import React, { useEffect, useRef, useState, useCallback } from "react";
import { api } from "../../../portal/api";
import { PageHeader, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import {
  MailPlus, Send, RefreshCw, Loader2, AlertTriangle, Settings, Save, X as XIcon,
  CheckCircle2, XCircle, PlugZap, Reply, ReplyAll, Forward, Trash2, Paperclip,
  Inbox as InboxIcon, FileEdit, ShieldAlert, Archive, Folder as FolderIcon,
  MailOpen, Mail as MailIcon, Download,
} from "lucide-react";

const FOLDER_ICONS = {
  inbox: InboxIcon, sent: Send, drafts: FileEdit, junk: ShieldAlert,
  trash: Trash2, archive: Archive, custom: FolderIcon,
};

const fmtSize = (b) => {
  const v = Number(b) || 0;
  if (v >= 1048576) return `${(v / 1048576).toFixed(1)} MB`;
  if (v >= 1024) return `${(v / 1024).toFixed(0)} KB`;
  return `${v} B`;
};

/* ---- Render body HTML email di iframe sandbox (tanpa JS) ---- */
const HtmlBody = ({ html }) => {
  const ref = useRef(null);
  const doc = `<!doctype html><html><head><meta charset="utf-8"><base target="_blank">
<style>body{font-family:ui-sans-serif,system-ui,Segoe UI,sans-serif;font-size:14px;color:#1e293b;margin:0;padding:6px;word-break:break-word}img{max-width:100%;height:auto}table{max-width:100%}</style>
</head><body>${html}</body></html>`;
  return (
    <iframe
      ref={ref}
      title="email-body"
      sandbox="allow-same-origin allow-popups"
      srcDoc={doc}
      className="w-full border-0 bg-white"
      style={{ minHeight: 220 }}
      onLoad={() => {
        try {
          const h = ref.current.contentDocument.body.scrollHeight;
          ref.current.style.height = `${Math.min(Math.max(h + 30, 220), 1400)}px`;
        } catch { /* noop */ }
      }}
      data-testid="mail-html-body"
    />
  );
};

const AdminMail = () => {
  const [folders, setFolders] = useState(null);   // list | null
  const [folder, setFolder] = useState("INBOX");
  const [rows, setRows] = useState(null);         // list OR { not_setup, message }
  const [selected, setSelected] = useState(null);
  const [showCompose, setShowCompose] = useState(false);
  const [busyMsg, setBusyMsg] = useState("");

  const loadFolders = useCallback(async () => {
    try {
      const { data } = await api.get("/admin/mail/folders");
      if (Array.isArray(data)) setFolders(data);
      else setFolders([]);
    } catch { setFolders([]); }
  }, []);

  const loadMessages = useCallback(async (f) => {
    setRows(null);
    setSelected(null);
    try {
      const { data } = await api.get(`/admin/mail/inbox?folder=${encodeURIComponent(f)}`);
      setRows(data);
    } catch (e) {
      setRows({ not_setup: true, reason: "error", message: e?.response?.data?.detail || e.message });
    }
  }, []);

  useEffect(() => { loadFolders(); }, [loadFolders]);
  useEffect(() => { loadMessages(folder); }, [folder, loadMessages]);

  const currentRole = (folders || []).find((f) => f.id === folder)?.role || "inbox";

  const open = async (m) => {
    setSelected(m);
    try {
      const { data } = await api.get(`/admin/mail/messages/${m.id}?folder=${encodeURIComponent(folder)}`);
      setSelected(data);
      if (m.unread) {
        setRows((prev) => Array.isArray(prev) ? prev.map((x) => (x.id === m.id ? { ...x, unread: false } : x)) : prev);
        setFolders((prev) => Array.isArray(prev) ? prev.map((f) => (f.id === folder ? { ...f, unread: Math.max(0, (f.unread || 0) - 1) } : f)) : prev);
      }
    } catch (e) {
      setSelected({ ...m, body: m.preview || "(Gagal memuat isi pesan - cek koneksi IMAP atau refresh)" });
    }
  };

  const removeMsg = async (m) => {
    if (!window.confirm(currentRole === "trash" ? "Hapus permanen pesan ini?" : "Pindahkan pesan ke Trash?")) return;
    setBusyMsg(m.id);
    try {
      await api.delete(`/admin/mail/messages/${m.id}?folder=${encodeURIComponent(folder)}`);
      setRows((prev) => Array.isArray(prev) ? prev.filter((x) => x.id !== m.id) : prev);
      setSelected(null);
      loadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal menghapus pesan.");
    } finally { setBusyMsg(""); }
  };

  const markUnread = async (m) => {
    try {
      await api.post(`/admin/mail/messages/${m.id}/read?folder=${encodeURIComponent(folder)}`, { read: false });
      setRows((prev) => Array.isArray(prev) ? prev.map((x) => (x.id === m.id ? { ...x, unread: true } : x)) : prev);
      setSelected(null);
      loadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || "Gagal menandai pesan.");
    }
  };

  const notSetup = rows && !Array.isArray(rows) && rows.not_setup;
  const list = Array.isArray(rows) ? rows : [];

  const replyTo = (msg, all = false) => {
    const subj = msg.subject || "";
    const quoted = (msg.body || "").split("\n").map((l) => `> ${l}`).join("\n");
    const cc = all ? [msg.to, msg.cc].filter(Boolean).join(", ") : "";
    setShowCompose({
      to: msg.from_email || "",
      cc,
      subject: /^re:/i.test(subj) ? subj : `Re: ${subj}`,
      body: `\n\n--- Pesan asli dari ${msg.from_email || ""} (${msg.received_at || ""}) ---\n${quoted}`,
    });
  };

  const forward = (msg) => {
    const subj = msg.subject || "";
    const quoted = (msg.body || "").split("\n").map((l) => `> ${l}`).join("\n");
    setShowCompose({
      to: "",
      subject: /^fwd:/i.test(subj) ? subj : `Fwd: ${subj}`,
      body: `\n\n--- Pesan diteruskan dari ${msg.from_email || ""} ---\nSubject: ${subj}\n\n${quoted}`,
    });
  };

  const editDraft = (msg) => {
    setShowCompose({
      to: msg.to || "", cc: msg.cc || "",
      subject: msg.subject || "", body: msg.body || "",
    });
  };

  const [showSetup, setShowSetup] = useState(false);

  return (
    <div>
      <PageHeader
        title="Webmail"
        subtitle="Inbox pribadi Anda - setiap staff punya credential cPanel IMAP/SMTP sendiri."
        actions={
          <div className="flex gap-2">
            <button className={btnSecondary} onClick={() => { loadFolders(); loadMessages(folder); }} data-testid="mail-refresh-btn">
              <RefreshCw className="h-4 w-4" /> Refresh
            </button>
            <button className={btnSecondary} onClick={() => setShowSetup(true)} data-testid="mail-setup-btn">
              <Settings className="h-4 w-4" /> Setup Email
            </button>
            <button className={btnPrimary} onClick={() => setShowCompose(true)} data-testid="mail-compose-btn">
              <MailPlus className="h-4 w-4" /> Compose
            </button>
          </div>
        }
      />

      {rows === null && !notSetup && (
        <div className="text-center text-slate-500 py-16 flex items-center justify-center gap-2">
          <Loader2 className="h-5 w-5 animate-spin" /> Loading mailbox…
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

      {rows !== null && !notSetup && (
        <div className="grid grid-cols-12 gap-4">
          {/* -------- Folder sidebar -------- */}
          <div className="col-span-12 md:col-span-2 rounded-2xl bg-white border border-slate-200 p-2 h-fit" data-testid="mail-folders">
            {(folders || []).map((f) => {
              const Icon = FOLDER_ICONS[f.role] || FolderIcon;
              const active = f.id === folder;
              return (
                <button
                  key={f.id}
                  onClick={() => setFolder(f.id)}
                  data-testid={`mail-folder-${f.role}-${f.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm mb-0.5 ${
                    active ? "bg-[#0a2350] text-white font-bold" : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  <Icon className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate flex-1 text-left">{f.name}</span>
                  {f.unread > 0 && (
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${active ? "bg-[#f5b120] text-[#0a2350]" : "bg-[#0a2350]/10 text-[#0a2350]"}`}>
                      {f.unread}
                    </span>
                  )}
                </button>
              );
            })}
            {(folders || []).length === 0 && (
              <div className="text-xs text-slate-400 px-3 py-2">Folder tidak termuat.</div>
            )}
          </div>

          {/* -------- Message list -------- */}
          <div className="col-span-12 md:col-span-4 rounded-2xl bg-white border border-slate-200 max-h-[72vh] overflow-y-auto" data-testid="mail-list">
            {list.length === 0 && (
              <div className="text-center text-slate-400 text-sm py-16">Folder kosong.</div>
            )}
            {list.map((m) => (
              <button key={m.id}
                onClick={() => open(m)}
                data-testid={`mail-${m.id}`}
                className={`w-full text-left px-4 py-3 border-b border-slate-100 hover:bg-slate-50 ${
                  selected?.id === m.id ? "bg-slate-100" : ""
                }`}>
                <div className="flex justify-between items-baseline">
                  <div className={`text-sm truncate ${m.unread ? "font-bold text-[#0a2350]" : "text-slate-700"}`}>
                    {currentRole === "sent" || currentRole === "drafts" ? (m.to || m.from_name || m.from_email) : (m.from_name || m.from_email)}
                  </div>
                  <div className="text-[10px] text-slate-400 whitespace-nowrap ml-2">
                    {m.received_at ? new Date(m.received_at).toLocaleDateString() : ""}
                  </div>
                </div>
                <div className={`text-sm truncate flex items-center gap-1.5 ${m.unread ? "font-semibold" : ""}`}>
                  {m.has_attachments && <Paperclip className="h-3 w-3 text-slate-400 flex-shrink-0" data-testid={`mail-attach-icon-${m.id}`} />}
                  <span className="truncate">{m.subject || "(tanpa subjek)"}</span>
                </div>
                <div className="text-xs text-slate-500 truncate">{m.preview}</div>
              </button>
            ))}
          </div>

          {/* -------- Detail pane -------- */}
          <div className="col-span-12 md:col-span-6 rounded-2xl bg-white border border-slate-200 p-5 min-h-[72vh] max-h-[72vh] overflow-y-auto" data-testid="mail-detail">
            {selected ? (
              <>
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="min-w-0">
                    <div className="text-xs text-slate-500 truncate">From: <span className="font-mono">{selected.from_email}</span></div>
                    {selected.to && <div className="text-xs text-slate-500 truncate">To: <span className="font-mono">{selected.to}</span></div>}
                    {selected.cc && <div className="text-xs text-slate-500 truncate">Cc: <span className="font-mono">{selected.cc}</span></div>}
                    <div className="text-lg font-bold text-[#0a2350] break-words">{selected.subject}</div>
                    <div className="text-[11px] text-slate-400">{selected.received_at || ""}</div>
                  </div>
                  <div className="flex gap-1.5 flex-shrink-0 flex-wrap justify-end">
                    {currentRole === "drafts" ? (
                      <button className={btnPrimary} onClick={() => editDraft(selected)} data-testid="mail-edit-draft-btn">
                        <FileEdit className="h-4 w-4" /> Lanjutkan Draft
                      </button>
                    ) : (
                      <>
                        <button className={btnSecondary} onClick={() => replyTo(selected)} title="Reply" data-testid="mail-reply-btn">
                          <Reply className="h-4 w-4" />
                        </button>
                        <button className={btnSecondary} onClick={() => replyTo(selected, true)} title="Reply All" data-testid="mail-replyall-btn">
                          <ReplyAll className="h-4 w-4" />
                        </button>
                        <button className={btnSecondary} onClick={() => forward(selected)} title="Forward" data-testid="mail-forward-btn">
                          <Forward className="h-4 w-4" />
                        </button>
                        <button className={btnSecondary} onClick={() => markUnread(selected)} title="Tandai belum dibaca" data-testid="mail-unread-btn">
                          <MailIcon className="h-4 w-4" />
                        </button>
                      </>
                    )}
                    <button
                      className="inline-flex items-center gap-1.5 rounded-xl border border-red-200 bg-red-50 text-red-600 hover:bg-red-100 px-3 py-2 text-sm font-bold"
                      onClick={() => removeMsg(selected)}
                      disabled={busyMsg === selected.id}
                      title="Hapus"
                      data-testid="mail-delete-btn"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {(selected.attachments || []).length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-2" data-testid="mail-attachments">
                    {selected.attachments.map((a) => (
                      <AttachmentChip key={a.index} att={a} messageId={selected.id} folder={folder} />
                    ))}
                  </div>
                )}

                {selected.body_html ? (
                  <HtmlBody html={selected.body_html} />
                ) : (
                  <div className="whitespace-pre-wrap text-sm text-slate-700 leading-relaxed" data-testid="mail-text-body">
                    {selected.body || "(no body)"}
                  </div>
                )}
              </>
            ) : (
              <div className="text-slate-400 text-sm text-center py-20 flex flex-col items-center gap-2">
                <MailOpen className="h-8 w-8 text-slate-300" />
                Pilih pesan untuk melihat isi
              </div>
            )}
          </div>
        </div>
      )}

      {showSetup && <SetupEmailModal onClose={() => setShowSetup(false)} onDone={() => { setShowSetup(false); loadFolders(); loadMessages(folder); }} />}
      {showCompose && (
        <ComposeModal
          initial={typeof showCompose === "object" ? showCompose : null}
          onClose={() => setShowCompose(false)}
          onSent={() => { loadFolders(); if (folder === "INBOX") loadMessages(folder); }}
          onNeedSetup={() => { setShowCompose(false); setShowSetup(true); }}
        />
      )}
    </div>
  );
};

const AttachmentChip = ({ att, messageId, folder }) => {
  const [busy, setBusy] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      const res = await api.get(
        `/admin/mail/messages/${messageId}/attachments/${att.index}?folder=${encodeURIComponent(folder)}`,
        { responseType: "blob" });
      const url = URL.createObjectURL(res.data);
      const a = document.createElement("a");
      a.href = url; a.download = att.filename || "attachment"; a.click();
      URL.revokeObjectURL(url);
    } catch { alert("Gagal mengunduh lampiran."); } finally { setBusy(false); }
  };
  return (
    <button
      onClick={download}
      disabled={busy}
      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 hover:bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700"
      data-testid={`mail-attachment-${att.index}`}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
      {att.filename} <span className="text-slate-400">({fmtSize(att.size)})</span>
    </button>
  );
};

const ComposeModal = ({ onClose, onNeedSetup, onSent, initial }) => {
  const [form, setForm] = useState({
    to: initial?.to || "",
    cc: initial?.cc || "",
    bcc: initial?.bcc || "",
    subject: initial?.subject || "",
    body: initial?.body || "",
  });
  const [showCc, setShowCc] = useState(!!initial?.cc);
  const [showBcc, setShowBcc] = useState(!!initial?.bcc);
  const [atts, setAtts] = useState([]); // {filename, mime, size, content_base64}
  const [busy, setBusy] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [err, setErr] = useState("");
  const [needSetup, setNeedSetup] = useState(false);
  const [sent, setSent] = useState(null);
  const fileRef = useRef(null);

  const totalSize = atts.reduce((s, a) => s + (a.size || 0), 0);

  const addFiles = (files) => {
    [...files].forEach((f) => {
      if (totalSize + f.size > 15 * 1024 * 1024) {
        setErr("Total lampiran melebihi 15 MB.");
        return;
      }
      const reader = new FileReader();
      reader.onload = () => setAtts((prev) => [...prev, {
        filename: f.name,
        mime: f.type || "application/octet-stream",
        size: f.size,
        content_base64: String(reader.result).split(",")[1] || "",
      }]);
      reader.readAsDataURL(f);
    });
  };

  const payload = () => ({ ...form, attachments: atts.map(({ size, ...rest }) => rest) });

  const send = async () => {
    setBusy(true); setErr(""); setNeedSetup(false);
    try {
      const { data } = await api.post("/admin/mail/send", payload());
      setSent(data);
      onSent && onSent();
    } catch (e) {
      const detail = e?.response?.data?.detail || e.message;
      setErr(detail);
      if (e?.response?.status === 400 && /setup smtp/i.test(detail)) setNeedSetup(true);
    } finally { setBusy(false); }
  };

  const saveDraft = async () => {
    setSavingDraft(true); setErr("");
    try {
      await api.post("/admin/mail/drafts", payload());
      onSent && onSent();
      onClose();
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setSavingDraft(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="mail-compose-modal">
        <div className="flex justify-between items-start mb-3">
          <div className="text-lg font-bold text-[#0a2350]">Compose</div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-800"><XIcon className="h-5 w-5" /></button>
        </div>

        {sent ? (
          <div className="text-center py-6" data-testid="mail-compose-sent">
            <div className="mx-auto h-12 w-12 rounded-2xl bg-emerald-500/15 flex items-center justify-center mb-3">
              <Send className="h-6 w-6 text-emerald-600" />
            </div>
            <div className="text-lg font-bold text-emerald-700 mb-1">Email terkirim!</div>
            <div className="text-sm text-slate-500">
              Terkirim ke <span className="font-mono">{form.to}</span> via SMTP Anda.
              {sent.saved_to_sent_folder && <span className="block text-xs mt-1 text-slate-400">Salinan tersimpan di folder Sent.</span>}
            </div>
            <div className="mt-4"><button className={btnPrimary} onClick={onClose}>Tutup</button></div>
          </div>
        ) : (
          <>
            {err && (
              <div className="mb-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2" data-testid="mail-compose-error">
                {err}
                {needSetup && (
                  <button className="block mt-2 underline font-semibold" onClick={onNeedSetup} data-testid="mail-compose-goto-setup">
                    Buka Setup Email →
                  </button>
                )}
              </div>
            )}
            <div className="space-y-3">
              <label className="block">
                <div className={`${labelClass} flex items-center justify-between`}>
                  <span>To</span>
                  <span className="flex gap-2 normal-case tracking-normal">
                    {!showCc && <button className="text-[11px] font-bold text-[#0a2350]/70 hover:text-[#0a2350]" onClick={(e) => { e.preventDefault(); setShowCc(true); }} data-testid="mail-compose-show-cc">+ Cc</button>}
                    {!showBcc && <button className="text-[11px] font-bold text-[#0a2350]/70 hover:text-[#0a2350]" onClick={(e) => { e.preventDefault(); setShowBcc(true); }} data-testid="mail-compose-show-bcc">+ Bcc</button>}
                  </span>
                </div>
                <input className={inputClass} value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} placeholder="tujuan@contoh.com, lainnya@contoh.com" data-testid="mail-compose-to" />
              </label>
              {showCc && (
                <label className="block"><div className={labelClass}>Cc</div>
                  <input className={inputClass} value={form.cc} onChange={(e) => setForm({ ...form, cc: e.target.value })} placeholder="cc@contoh.com" data-testid="mail-compose-cc" /></label>
              )}
              {showBcc && (
                <label className="block"><div className={labelClass}>Bcc</div>
                  <input className={inputClass} value={form.bcc} onChange={(e) => setForm({ ...form, bcc: e.target.value })} placeholder="bcc@contoh.com" data-testid="mail-compose-bcc" /></label>
              )}
              <label className="block"><div className={labelClass}>Subject</div>
                <input className={inputClass} value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} placeholder="Subjek email" data-testid="mail-compose-subject" /></label>
              <label className="block"><div className={labelClass}>Message</div>
                <textarea className={`${inputClass} min-h-[140px]`} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} placeholder="Tulis pesan Anda…" data-testid="mail-compose-body" /></label>

              {/* Attachments */}
              <div>
                <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} data-testid="mail-compose-file-input" />
                <button className={btnSecondary} onClick={() => fileRef.current?.click()} data-testid="mail-compose-attach-btn">
                  <Paperclip className="h-4 w-4" /> Lampirkan file
                </button>
                {atts.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2" data-testid="mail-compose-attachments">
                    {atts.map((a, i) => (
                      <span key={i} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700">
                        <Paperclip className="h-3 w-3 text-slate-400" />
                        {a.filename} <span className="text-slate-400">({fmtSize(a.size)})</span>
                        <button onClick={() => setAtts((prev) => prev.filter((_, j) => j !== i))} className="text-slate-400 hover:text-red-500" data-testid={`mail-compose-attachment-remove-${i}`}>
                          <XIcon className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                    <span className="text-[11px] text-slate-400 self-center">{fmtSize(totalSize)} / 15 MB</span>
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-between gap-2 mt-4">
              <button className={btnSecondary} onClick={saveDraft} disabled={savingDraft || busy} data-testid="mail-compose-save-draft">
                {savingDraft ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Simpan Draft
              </button>
              <div className="flex gap-2">
                <button className={btnSecondary} onClick={onClose}>Batal</button>
                <button className={btnPrimary} onClick={send} disabled={busy || savingDraft || !form.to || !form.subject} data-testid="mail-compose-send">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Kirim
                </button>
              </div>
            </div>
          </>
        )}
      </div>
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
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // { ok, imap:{ok,message}, smtp:{ok,message} }

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

  const testConnection = async () => {
    setTesting(true); setErr(""); setTestResult(null);
    try {
      const { data } = await api.post("/settings/email/test", form);
      setTestResult(data);
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message);
    } finally { setTesting(false); }
  };

  const setField = (kind, key, value) => setForm({ ...form, [kind]: { ...form[kind], [key]: value } });

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="mail-setup-modal">
        <div className="flex justify-between items-start mb-4">
          <div>
            <div className="text-xl font-extrabold text-[#0a2350]">Setup Email Pribadi (cPanel)</div>
            <div className="text-sm text-slate-500">Kredensial ini hanya untuk akun Anda - admin lain tidak bisa melihatnya.</div>
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
            {testResult && (
              <div className="mb-4 rounded-xl border border-slate-200 divide-y divide-slate-100" data-testid="mail-test-results">
                {["imap", "smtp"].map((kind) => {
                  const r = testResult[kind] || {};
                  return (
                    <div key={kind} className="flex items-start gap-3 px-4 py-3" data-testid={`mail-test-${kind}`}>
                      <div className={`mt-0.5 h-6 w-6 rounded-full flex items-center justify-center flex-shrink-0 ${r.ok ? "bg-emerald-500/15" : "bg-red-500/15"}`}>
                        {r.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-red-600" />}
                      </div>
                      <div className="min-w-0">
                        <div className={`text-sm font-bold ${r.ok ? "text-emerald-700" : "text-red-700"}`}>
                          {kind.toUpperCase()} {r.ok ? "- koneksi berhasil" : "- gagal"}
                        </div>
                        <div className="text-xs text-slate-500 break-words">{r.message}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="flex justify-between gap-2">
              <button className={btnSecondary} onClick={testConnection} disabled={testing || busy} data-testid="mail-setup-test">
                {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test Connection
              </button>
              <div className="flex gap-2">
                <button className={btnSecondary} onClick={onClose}>Batal</button>
                <button className={btnPrimary} onClick={save} disabled={busy || testing} data-testid="mail-setup-save">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Simpan
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default AdminMail;
