import React, { useState, useEffect, useMemo } from "react";
import { api } from "../../portal/api";
import Modal from "./Modal";
import { btnPrimary, btnSecondary, labelClass, inputClass } from "../../pages/portal/ui";
import { Link2, Lock, Trash2, Copy, Check } from "lucide-react";

const PERM_OPTIONS = [
  { key: "read", label: "Read-only" },
  { key: "download", label: "Download" },
  { key: "delete", label: "Delete" },
  { key: "manage", label: "Manage" },
];

/**
 * Folder sharing modal — two modes:
 *  1. Password-protected public link (share-links API)
 *  2. Granular ACL (user/division/role with read/download/delete/manage)
 */
const ShareFolderModal = ({ folder, onClose, onSaved }) => {
  const [users, setUsers] = useState([]);
  const [acl, setAcl] = useState([]); // [{principal_type, principal_id, perms:[]}]
  const [password, setPassword] = useState("");
  const [expiresDays, setExpiresDays] = useState("");
  const [links, setLinks] = useState([]);
  const [newToken, setNewToken] = useState(null); // shown once after create
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("name");

  // Load staff directory + existing share links
  useEffect(() => {
    api.get("/admin/staff-directory/users").then((r) => {
      const items = r.data?.items || (Array.isArray(r.data) ? r.data : []);
      setUsers(items.map((u) => ({
        id: String(u.id), name: u.name || u.email || "(tanpa nama)",
        email: u.email || "", division: (u.division || "").trim(),
      })));
    }).catch(() => setUsers([]));

    api.get(`/admin/document-folders/${folder.id}/share-links`).then((r) => {
      setLinks(r.data || []);
    }).catch(() => setLinks([]));

    // Pre-fill ACL from folder (if any)
    const existing = (folder.acl || []).map((e) => ({
      principal_type: e.principal_type,
      principal_id: String(e.principal_id),
      perms: [...(e.perms || [])],
    }));
    setAcl(existing);
  }, [folder]);

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = users.filter((u) =>
      !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    );
    if (sortBy === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    else if (sortBy === "division") list.sort((a, b) => (a.division || "").localeCompare(b.division || ""));
    return list;
  }, [users, search, sortBy]);

  const toggleUser = (uid) => {
    setAcl((prev) => {
      const exists = prev.find((e) => e.principal_type === "user" && e.principal_id === uid);
      if (exists) return prev.filter((e) => !(e.principal_type === "user" && e.principal_id === uid));
      return [...prev, { principal_type: "user", principal_id: uid, perms: ["read"] }];
    });
  };

  const setUserPerms = (uid, perm) => {
    setAcl((prev) => prev.map((e) => {
      if (e.principal_type === "user" && e.principal_id === uid) {
        const has = e.perms.includes(perm);
        return { ...e, perms: has ? e.perms.filter((p) => p !== perm) : [...e.perms, perm] };
      }
      return e;
    }));
  };

  const saveAcl = async () => {
    setBusy(true); setErr("");
    try {
      await api.patch(`/admin/document-folders-v2/${folder.id}`, { acl });
      onSaved();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal menyimpan hak akses");
    } finally { setBusy(false); }
  };

  const createLink = async () => {
    setBusy(true); setErr("");
    try {
      const payload = { perms: ["read", "download"] };
      if (password.trim()) payload.password = password.trim();
      if (expiresDays) payload.expires_in_days = Number(expiresDays);
      const r = await api.post(`/admin/document-folders/${folder.id}/share-links`, payload);
      setNewToken(r.data?.token || "");
      setPassword("");
      setExpiresDays("");
      // refresh links
      const l = await api.get(`/admin/document-folders/${folder.id}/share-links`);
      setLinks(l.data || []);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal membuat link");
    } finally { setBusy(false); }
  };

  const revokeLink = async (linkId) => {
    setBusy(true); setErr("");
    try {
      await api.delete(`/admin/document-folders/${folder.id}/share-links/${linkId}`);
      setLinks((prev) => prev.filter((l) => l.link_id !== linkId));
    } catch (e) {
      setErr(e?.response?.data?.detail || "Gagal mencabut link");
    } finally { setBusy(false); }
  };

  const copyToken = () => {
    navigator.clipboard?.writeText(newToken).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <Modal onClose={onClose} title={`Share folder: ${folder.name}`}>
      <div className="flex flex-col gap-4">
        {err && <div className="rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{err}</div>}

        {/* ===== Password-protected link ===== */}
        <div className="rounded-xl border border-slate-200 p-4">
          <div className="text-sm font-bold text-[#0a2350] mb-2 flex items-center gap-1.5">
            <Link2 className="h-4 w-4" /> Link sharing (opsional password)
          </div>
          <div className="flex gap-2 mb-2">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
              placeholder="Password (kosongkan utk link terbuka)"
              data-testid="folder-link-password"
            />
            <input
              type="number"
              value={expiresDays}
              onChange={(e) => setExpiresDays(e.target.value)}
              className={`${inputClass} w-28`}
              placeholder="Hari"
              title="Masa berlaku (hari)"
              data-testid="folder-link-expiry"
            />
          </div>
          <button className={btnPrimary} onClick={createLink} disabled={busy} data-testid="folder-link-create">
            <Lock className="h-3.5 w-3.5" /> Buat link
          </button>

          {newToken && (
            <div className="mt-3 rounded-lg bg-emerald-50 border border-emerald-200 p-3" data-testid="folder-link-token">
              <div className="text-xs font-bold text-emerald-700 mb-1">Token (tampil sekali — simpan sekarang):</div>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs break-all bg-white rounded px-2 py-1 border border-emerald-200">{newToken}</code>
                <button className="text-emerald-700 hover:text-emerald-900" onClick={copyToken} title="Copy">
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>
            </div>
          )}

          {links.length > 0 && (
            <div className="mt-3" data-testid="folder-links-list">
              <div className="text-xs font-bold text-slate-500 mb-1">Link aktif:</div>
              {links.map((l) => (
                <div key={l.link_id} className="flex items-center gap-2 text-xs py-1 border-b border-slate-100">
                  <span className="flex-1">
                    {l.requires_password ? "🔒" : "🔓"} {l.perms?.join(", ") || "read"}
                    {l.expires_at ? ` · sd ${new Date(l.expires_at).toLocaleDateString()}` : ""}
                  </span>
                  <button className="text-red-500 hover:text-red-700" onClick={() => revokeLink(l.link_id)} title="Cabut link">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ===== Granular ACL ===== */}
        <div className="rounded-xl border border-slate-200 p-4">
          <div className="text-sm font-bold text-[#0a2350] mb-2">Hak akses per user</div>

          <div className="flex gap-2 mb-2">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className={inputClass}
              placeholder="Cari user…"
              data-testid="folder-acl-search"
            />
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className={`${inputClass} w-36`} data-testid="folder-acl-sort">
              <option value="name">Nama</option>
              <option value="division">Divisi</option>
            </select>
          </div>

          <div className="max-h-52 overflow-y-auto border border-slate-200 rounded-xl p-2" data-testid="folder-acl-users">
            {filteredUsers.length === 0 && <div className="text-xs text-slate-400">Tidak ada user.</div>}
            {filteredUsers.map((u) => {
              const entry = acl.find((e) => e.principal_type === "user" && e.principal_id === u.id);
              const checked = !!entry;
              return (
                <div key={u.id} className="flex flex-col gap-1 py-1.5 border-b border-slate-50">
                  <label className="flex items-center gap-2 cursor-pointer text-sm">
                    <input type="checkbox" checked={checked} onChange={() => toggleUser(u.id)} />
                    <span className="flex-1 truncate">{u.name}{u.email ? ` · ${u.email}` : ""}</span>
                    {u.division && <span className="text-[10px] text-slate-400">{u.division}</span>}
                  </label>
                  {checked && (
                    <div className="flex flex-wrap gap-1 ml-6" data-testid={`folder-acl-perms-${u.id}`}>
                      {PERM_OPTIONS.map((p) => (
                        <button
                          key={p.key}
                          type="button"
                          onClick={() => setUserPerms(u.id, p.key)}
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                            entry.perms.includes(p.key)
                              ? "bg-[#0a2350] text-white border-[#0a2350]"
                              : "bg-white text-slate-500 border-slate-200"
                          }`}
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <button className={btnSecondary} onClick={onClose}>Tutup</button>
          <button className={btnPrimary} onClick={saveAcl} disabled={busy} data-testid="folder-acl-save">
            {busy ? "Menyimpan…" : "Simpan hak akses"}
          </button>
        </div>
      </div>
    </Modal>
  );
};

export default ShareFolderModal;
