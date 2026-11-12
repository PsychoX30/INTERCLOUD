import React, { useCallback, useEffect, useState } from "react";
import { Save, Loader2, Video, Copy, Trash2, RefreshCw, Plus } from "lucide-react";
import { api, fullDateTime, formatApiError } from "../../../portal/api";

const STATE_STYLE = {
  live: "bg-emerald-50 text-emerald-700 border-emerald-200",
  scheduled: "bg-sky-50 text-sky-700 border-sky-200",
  expired: "bg-amber-50 text-amber-700 border-amber-200",
  ended: "bg-slate-100 text-slate-500 border-slate-200",
};

const STATE_LABEL = {
  live: "Berlangsung",
  scheduled: "Terjadwal",
  expired: "Lewat",
  ended: "Diakhiri",
};

const inputCls =
  "w-full px-4 py-2 rounded-xl border border-slate-300 focus:border-[#f5b120] focus:ring-1 focus:ring-[#f5b120] outline-none";

export default function AdminJitsi() {
  // ---- config rapat (kontrak lama, jangan diubah: test_jitsi_contract.py) ----
  const [cfg, setCfg] = useState({
    enabled: false,
    domain: "meet.intercloud-digital.com",
    default_room_prefix: "intercloud",
    jwt_secret: "",
  });
  const [secretSet, setSecretSet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  // ---- registry rapat ----
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [includeEnded, setIncludeEnded] = useState(false);

  const [form, setForm] = useState({
    title: "",
    host_name: "",
    slug: "",
    starts_at: "",
    duration_min: 60,
    lobby: true,
  });
  const [creating, setCreating] = useState(false);

  // Tautan plaintext hanya keluar SEKALI (create / rotate). Tanpa panel ini,
  // tombolnya tidak ada gunanya -- begitu notifikasi hilang, tautan lenyap.
  const [invite, setInvite] = useState(null); // { url, text, slug, source }
  const [copied, setCopied] = useState(""); // "" | "link" | "text"

  const loadMeetings = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/admin/jitsi/meetings", {
        params: { include_ended: includeEnded },
      });
      setRows(data.items || []);
    } catch (e) {
      setMsg({ kind: "error", text: formatApiError(e) });
    } finally {
      setLoading(false);
    }
  }, [includeEnded]);

  useEffect(() => {
    api
      .get("/jitsi/config")
      .then(({ data }) => {
        // jwt_secret TIDAK pernah dikirim server; hanya flag jwt_secret_set.
        setSecretSet(!!data.jwt_secret_set);
        setCfg((prev) => ({ ...prev, ...data, jwt_secret: "" }));
      })
      .catch(() => {
        /* keep defaults */
      });
  }, []);

  useEffect(() => {
    loadMeetings();
  }, [loadMeetings]);

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const { data } = await api.post("/admin/jitsi/config", cfg);
      setSecretSet(!!data.jwt_secret_set);
      setCfg((prev) => ({ ...prev, ...data, jwt_secret: "" }));
      setMsg({
        kind: "ok",
        text: "Jitsi config saved – widget now " + (data.enabled ? "ACTIVE" : "INACTIVE"),
      });
    } catch (e) {
      setMsg({ kind: "error", text: formatApiError(e) });
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setCreating(true);
    setMsg(null);
    try {
      const payload = {
        title: form.title,
        duration_min: Number(form.duration_min) || 60,
        lobby: !!form.lobby,
      };
      if (form.host_name.trim()) payload.host_name = form.host_name.trim();
      if (form.slug.trim()) payload.slug = form.slug.trim();
      if (form.starts_at) {
        // datetime-local -> ISO UTC supaya backend tidak menebak zona waktu.
        payload.starts_at = new Date(form.starts_at).toISOString();
      }
      const { data } = await api.post("/admin/jitsi/meetings", payload);
      setInvite({
        url: data.invite_url,
        text: data.invite_text,
        slug: data.slug,
        source: "create",
      });
      setCopied("");
      setForm({ title: "", host_name: "", slug: "", starts_at: "", duration_min: 60, lobby: true });
      await loadMeetings();
    } catch (e) {
      setMsg({ kind: "error", text: formatApiError(e) });
    } finally {
      setCreating(false);
    }
  };

  const rotate = async (row) => {
    setMsg(null);
    try {
      const { data } = await api.post(`/admin/jitsi/meetings/${row.id}/rotate-invite`);
      setInvite({
        url: data.invite_url,
        text: data.invite_text,
        slug: row.slug,
        source: "rotate",
      });
      setCopied("");
      await loadMeetings();
    } catch (e) {
      setMsg({ kind: "error", text: formatApiError(e) });
    }
  };

  const end = async (row) => {
    if (!window.confirm(`Akhiri rapat "${row.title}"? Tautan undangan langsung mati.`)) return;
    setMsg(null);
    try {
      await api.post(`/admin/jitsi/meetings/${row.id}/end`);
      if (invite && invite.slug === row.slug) setInvite(null);
      await loadMeetings();
      setMsg({ kind: "ok", text: "Rapat diakhiri. Tautan lama sudah tidak berlaku." });
    } catch (e) {
      setMsg({ kind: "error", text: formatApiError(e) });
    }
  };

  // Clipboard API bisa ditolak (permission, iframe, context tidak aman).
  // Kalau `writeText` gagal kita TIDAK boleh diam: sebelumnya tombol hanya
  // berubah sebentar lalu kembali, tanpa jejak apa pun, dan user menyimpulkan
  // tombolnya rusak. Sekarang ada fallback `execCommand('copy')` lewat textarea
  // sementara, lalu pesan yang menetap kalau keduanya gagal.
  const copyToClipboard = async (value, which) => {
    if (!value) return;
    let ok = false;
    try {
      await navigator.clipboard.writeText(value);
      ok = true;
    } catch {
      ok = legacyCopy(value);
    }
    if (ok) {
      setCopied(which);
      setMsg({ kind: "ok", text: which === "text" ? "Undangan disalin." : "Tautan disalin." });
      window.setTimeout(() => setCopied(""), 2000);
    } else {
      setCopied("");
      setMsg({
        kind: "error",
        text: "Browser memblokir clipboard. Salin manual dari kotak di atas (pilih semua, Ctrl+C).",
      });
    }
  };

  const legacyCopy = (value) => {
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      // Posisi di luar layar tapi tetap fokusable; `display:none` membuat
      // select() gagal di sebagian browser.
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-1000px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, value.length);
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch {
      return false;
    }
  };

  const copyInvite = () => copyToClipboard(invite?.url, "link");
  const copyInviteText = () => copyToClipboard(invite?.text, "text");

  return (
    <div className="p-6 max-w-4xl mx-auto" data-testid="admin-jitsi-page">
      <h1 className="text-xl font-bold text-[#0a2350] mb-4">Jitsi Meet</h1>

      {msg && (
        <div
          className={`mb-4 p-3 rounded-lg text-sm ${
            msg.kind === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
          }`}
        >
          {msg.text}
        </div>
      )}

      {/* ---------- buat rapat ---------- */}
      <section className="border border-slate-200 rounded-2xl p-5 mb-6">
        <h2 className="font-bold text-[#0a2350] mb-3 flex items-center gap-2">
          <Plus className="h-4 w-4" /> Buat rapat
        </h2>
        <div className="grid sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-[#0a2350] mb-1">Judul</label>
            <input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Rapat mingguan tim"
              className={inputCls}
              data-testid="jitsi-title"
            />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-[#0a2350] mb-1">
              Pembuat Meeting
            </label>
            <input
              value={form.host_name}
              onChange={(e) => setForm({ ...form, host_name: e.target.value })}
              placeholder="Nama yang tampil di undangan, mis. Budi Santoso"
              className={inputCls}
              data-testid="jitsi-host-name"
            />
            <p className="mt-1 text-slate-500 text-xs">
              Kosongkan untuk memakai email akun Anda.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-[#0a2350] mb-1">Slug (opsional)</label>
            <input
              value={form.slug}
              onChange={(e) => setForm({ ...form, slug: e.target.value })}
              placeholder="weekly-team"
              className={inputCls}
              data-testid="jitsi-slug"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#0a2350] mb-1">Mulai</label>
            <input
              type="datetime-local"
              value={form.starts_at}
              onChange={(e) => setForm({ ...form, starts_at: e.target.value })}
              className={inputCls}
              data-testid="jitsi-starts"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-[#0a2350] mb-1">Durasi (menit)</label>
            <input
              type="number"
              min={5}
              max={480}
              value={form.duration_min}
              onChange={(e) => setForm({ ...form, duration_min: e.target.value })}
              className={inputCls}
              data-testid="jitsi-duration"
            />
          </div>
          <label className="flex items-center gap-3 cursor-pointer self-end pb-2">
            <input
              type="checkbox"
              checked={form.lobby}
              onChange={(e) => setForm({ ...form, lobby: e.target.checked })}
              className="h-5 w-5 rounded border-slate-300 text-[#f5b120] focus:ring-[#f5b120]"
            />
            <span className="text-sm font-medium text-[#0a2350]">Ruang tunggu (lobby)</span>
          </label>
        </div>
        <button
          onClick={create}
          disabled={creating || !form.title.trim()}
          className="mt-4 px-5 py-2 rounded-lg bg-[#0a2350] text-white font-semibold hover:bg-[#1a355c] disabled:opacity-50 inline-flex items-center gap-2"
          data-testid="jitsi-create"
        >
          {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
          Buat rapat
        </button>
      </section>

      {/* ---------- tautan undangan (plaintext sekali) ---------- */}
      {invite && (
        <section className="border border-[#f5b120] bg-amber-50/60 rounded-2xl p-5 mb-6" data-testid="jitsi-invite">
          <h2 className="font-bold text-[#0a2350] mb-1">
            Undangan rapat ({invite.source === "rotate" ? "baru" : "dibuat"})
          </h2>
          <p className="text-slate-600 text-xs mb-3">
            Tautan ini hanya ditampilkan sekali. Salin sekarang — setelah ditutup, gunakan
            &ldquo;Undangan baru&rdquo; untuk menerbitkan tautan lain (tautan ini langsung mati).
          </p>

          <div className="flex flex-wrap gap-2 mb-3">
            <button
              onClick={copyInviteText}
              className="px-4 py-2 rounded-lg bg-[#f5b120] text-[#0a2350] font-semibold hover:brightness-95 inline-flex items-center gap-2"
              data-testid="jitsi-copy-invitation"
            >
              <Copy className="h-4 w-4" /> {copied === "text" ? "Undangan tersalin" : "Salin undangan"}
            </button>
            <button
              onClick={copyInvite}
              className="px-4 py-2 rounded-lg border border-[#0a2350] text-[#0a2350] font-semibold hover:bg-white inline-flex items-center gap-2"
              data-testid="jitsi-copy"
            >
              <Copy className="h-4 w-4" /> {copied === "link" ? "Tautan tersalin" : "Salin tautan saja"}
            </button>
          </div>

          <label className="block text-xs font-semibold text-[#0a2350] mb-1">
            Teks undangan
          </label>
          <textarea
            readOnly
            value={invite.text || ""}
            rows={14}
            onFocus={(e) => e.target.select()}
            className="w-full text-xs font-mono bg-white border border-slate-200 rounded-lg p-3 leading-relaxed"
            data-testid="jitsi-invite-text"
          />

          <label className="block text-xs font-semibold text-[#0a2350] mb-1 mt-3">
            Tautan undangan
          </label>
          <code className="block text-xs break-all bg-white border border-slate-200 rounded-lg p-3">
            {invite.url}
          </code>
        </section>
      )}

      {/* ---------- daftar rapat ---------- */}
      <section className="border border-slate-200 rounded-2xl p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold text-[#0a2350]">Daftar rapat</h2>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={includeEnded}
                onChange={(e) => setIncludeEnded(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-[#f5b120] focus:ring-[#f5b120]"
              />
              Tampilkan yang diakhiri
            </label>
            <button
              onClick={loadMeetings}
              className="p-2 rounded-lg border border-slate-200 hover:bg-slate-50"
              title="Muat ulang"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {rows.length === 0 ? (
          <p className="text-slate-500 text-sm py-4" data-testid="jitsi-empty">
            {loading ? "Memuat…" : "Belum ada rapat."}
          </p>
        ) : (
          <div className="space-y-2">
            {rows.map((r) => (
              <div
                key={r.id}
                className="flex flex-wrap items-center gap-3 border border-slate-200 rounded-xl px-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-[#0a2350] text-sm truncate">{r.title}</div>
                  <div className="text-xs text-slate-500">
                    {r.slug} · {fullDateTime(r.starts_at)} · {r.duration_min} mnt
                    {r.lobby ? " · lobby" : ""}
                  </div>
                </div>
                <span
                  className={`text-[11px] px-2 py-1 rounded-full border ${
                    STATE_STYLE[r.state] || STATE_STYLE.scheduled
                  }`}
                >
                  {STATE_LABEL[r.state] || r.state}
                </span>
                {r.invite_key_set && r.state !== "ended" && (
                  <button
                    onClick={() => rotate(r)}
                    className="px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold hover:bg-slate-50 inline-flex items-center gap-1"
                    title="Terbitkan undangan baru; tautan lama langsung mati"
                    data-testid={`jitsi-rotate-${r.slug}`}
                  >
                    <RefreshCw className="h-3.5 w-3.5" /> Undangan baru
                  </button>
                )}
                {r.state !== "ended" && (
                  <button
                    onClick={() => end(r)}
                    className="px-3 py-1.5 rounded-lg border border-red-200 text-red-600 text-xs font-semibold hover:bg-red-50 inline-flex items-center gap-1"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Akhiri
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ---------- konfigurasi (kontrak lama) ---------- */}
      <section className="border border-slate-200 rounded-2xl p-5">
        <h2 className="font-bold text-[#0a2350] mb-3">Konfigurasi</h2>
        <p className="text-slate-500 mb-6 text-sm">
          Domain dan prefix ruangan yang dipakai registry. Disimpan di CMS.
        </p>

        <div className="space-y-4">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={cfg.enabled}
              onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
              className="h-5 w-5 rounded border-slate-300 text-[#f5b120] focus:ring-[#f5b120]"
            />
            <span className="text-sm font-medium text-[#0a2350]">Enabled</span>
          </label>

          <div>
            <label className="block text-sm font-medium text-[#0a2350] mb-1">Domain</label>
            <input
              value={cfg.domain}
              onChange={(e) => setCfg({ ...cfg, domain: e.target.value })}
              placeholder="meet.intercloud-digital.com"
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[#0a2350] mb-1">Room prefix</label>
            <input
              value={cfg.default_room_prefix}
              onChange={(e) => setCfg({ ...cfg, default_room_prefix: e.target.value })}
              placeholder="intercloud"
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[#0a2350] mb-1">JWT secret (optional)</label>
            <input
              value={cfg.jwt_secret}
              onChange={(e) => setCfg({ ...cfg, jwt_secret: e.target.value })}
              placeholder={secretSet ? "•••••••• (sudah tersimpan)" : "belum ada secret"}
              autoComplete="new-password"
              className={inputCls}
            />
            <p className="mt-2 text-slate-500 text-xs">
              Secret tidak pernah dikirim balik oleh server. Biarkan kosong untuk mempertahankan
              secret yang sudah tersimpan; isi untuk menggantinya.
            </p>
          </div>
        </div>

        <button
          onClick={save}
          disabled={busy}
          className="mt-6 px-5 py-2 rounded-lg bg-[#0a2350] text-white font-semibold hover:bg-[#1a355c] disabled:opacity-50 inline-flex items-center gap-2"
          data-testid="jitsi-save"
        >
          <Save className="h-4 w-4" /> {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Simpan"}
        </button>
      </section>
    </div>
  );
}
