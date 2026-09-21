import React, { useState, useEffect, useMemo } from "react";
import { api } from "../../portal/api";
import Modal from "./Modal";
import { btnPrimary, btnSecondary, labelClass, inputClass } from "../../pages/portal/ui";

const STAFF_ROLES = [
  { key: "admin", label: "Admin" },
  { key: "owner", label: "Owner" },
  { key: "sales", label: "Sales" },
  { key: "finance", label: "Finance" },
  { key: "support", label: "Support" },
  { key: "ticket_only", label: "Ticket" },
  { key: "creative", label: "Creative" },
];

const PERM_OPTIONS = [
  { key: "read", label: "Read-only" },
  { key: "download", label: "Download" },
  { key: "delete", label: "Delete" },
  { key: "manage", label: "Manage" },
];

const ShareModal = ({ doc, onClose, onSaved }) => {
  const [users, setUsers] = useState([]);
  const [selUsers, setSelUsers] = useState({}); // uid -> perms[]
  const [selDivisions, setSelDivisions] = useState([]);
  const [selRoles, setSelRoles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("name");

  useEffect(() => {
    // Legacy share_with.users are plain ids; default perms = read+download.
    const init = {};
    ((doc.share_with?.users || []).map(String)).forEach((uid) => { init[uid] = ["read", "download"]; });
    // New ACL entries carry granular perms.
    ((doc.acl || []).filter((e) => e.principal_type === "user")).forEach((e) => {
      init[String(e.principal_id)] = [...(e.perms || [])];
    });
    setSelUsers(init);
    setSelDivisions(doc.share_with?.divisions || []);
    setSelRoles(doc.share_with?.roles || []);
    // Staff-only directory (excludes client accounts). Falls back to legacy.
    api.get("/admin/staff-directory/users").then((r) => {
      const items = r.data?.items || (Array.isArray(r.data) ? r.data : []);
      setUsers(items.map((u) => ({
        id: String(u.id), name: u.name || u.email || "(tanpa nama)",
        email: u.email || "", division: (u.division || "").trim(),
      })));
    }).catch(() => {
      api.get("/admin/users").then((r) => {
        const items = r.data?.items || (Array.isArray(r.data) ? r.data : []);
        setUsers(items.map((u) => ({
          id: String(u.id), name: u.name || u.email || "(tanpa nama)",
          email: u.email || "", division: (u.division || "").trim(),
        })));
      }).catch(() => setUsers([]));
    });
  }, [doc]);

  const filteredUsers = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = users.filter((u) =>
      !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
    );
    if (sortBy === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    else if (sortBy === "division") list.sort((a, b) => (a.division || "").localeCompare(b.division || ""));
    return list;
  }, [users, search, sortBy]);

  const toggle = (setter) => (val) =>
    setter((p) => (p.includes(val) ? p.filter((x) => x !== val) : [...p, val]));

  const toggleUser = (uid) => {
    setSelUsers((prev) => {
      const next = { ...prev };
      if (next[uid]) delete next[uid];
      else next[uid] = ["read", "download"];
      return next;
    });
  };

  const setUserPerms = (uid, perm) => {
    setSelUsers((prev) => {
      const cur = prev[uid] || [];
      const has = cur.includes(perm);
      return { ...prev, [uid]: has ? cur.filter((p) => p !== perm) : [...cur, perm] };
    });
  };

  const divisions = Array.from(new Set(users.map((u) => u.division).filter(Boolean)));

  const save = async () => {
    setBusy(true); setErr("");
    try {
      await api.patch(`/admin/documents/${doc.id}`, {
        share_with: {
          users: Object.keys(selUsers),
          divisions: selDivisions,
          roles: selRoles,
        },
        acl: [
          ...Object.entries(selUsers).map(([uid, perms]) => ({
            principal_type: "user", principal_id: uid, perms,
          })),
          ...selDivisions.map((d) => ({ principal_type: "division", principal_id: d, perms: ["read", "download"] })),
          ...selRoles.map((r) => ({ principal_type: "role", principal_id: r, perms: ["read", "download"] })),
        ],
      });
      onSaved();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Gagal menyimpan sharing");
    } finally { setBusy(false); }
  };

  return (
    <Modal onClose={onClose} title={`Share: ${doc.title}`}>
      <div className="flex flex-col gap-4">
        {err && <div className="rounded-xl bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2" data-testid="share-error">{err}</div>}
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className={labelClass}>User</div>
            <div className="flex gap-2">
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className={`${inputClass} h-8 w-40 text-xs`}
                placeholder="Cari user…"
                data-testid="share-user-search"
              />
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className={`${inputClass} h-8 w-28 text-xs`} data-testid="share-user-sort">
                <option value="name">Nama</option>
                <option value="division">Divisi</option>
              </select>
            </div>
          </div>
          <div className="max-h-52 overflow-y-auto border border-slate-200 rounded-xl p-2" data-testid="share-users">
            {filteredUsers.length === 0 && <div className="text-xs text-slate-400">Tidak ada user / gagal memuat.</div>}
            {filteredUsers.map((u) => {
              const perms = selUsers[u.id] || null;
              return (
                <div key={u.id} className="flex flex-col gap-1 py-1 border-b border-slate-50">
                  <label className="flex items-center gap-2 px-1 rounded hover:bg-slate-50 cursor-pointer text-sm">
                    <input type="checkbox" checked={!!perms} onChange={() => toggleUser(u.id)} />
                    <span className="flex-1 truncate">{u.name}{u.email ? ` · ${u.email}` : ""}</span>
                    {u.division && <span className="text-[10px] text-slate-400">{u.division}</span>}
                  </label>
                  {perms && (
                    <div className="flex flex-wrap gap-1 ml-6">
                      {PERM_OPTIONS.map((p) => (
                        <button
                          key={p.key}
                          type="button"
                          onClick={() => setUserPerms(u.id, p.key)}
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                            perms.includes(p.key)
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
        {divisions.length > 0 && (
          <div>
            <div className={labelClass}>Divisi</div>
            <div className="flex flex-wrap gap-2" data-testid="share-divisions">
              {divisions.map((d) => (
                <button key={d} type="button" onClick={() => toggle(setSelDivisions)(d)}
                        className={`px-3 py-1 rounded-full text-xs font-bold border ${selDivisions.includes(d) ? "bg-[#0a2350] text-white border-[#0a2350]" : "bg-white text-slate-600 border-slate-200"}`}>
                  {d}
                </button>
              ))}
            </div>
          </div>
        )}
        <div>
          <div className={labelClass}>Role</div>
          <div className="flex flex-wrap gap-2" data-testid="share-roles">
            {STAFF_ROLES.map((r) => (
              <button key={r.key} type="button" onClick={() => toggle(setSelRoles)(r.key)}
                      className={`px-3 py-1 rounded-full text-xs font-bold border ${selRoles.includes(r.key) ? "bg-[#0a2350] text-white border-[#0a2350]" : "bg-white text-slate-600 border-slate-200"}`}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="button" className={btnPrimary} disabled={busy} onClick={save} data-testid="share-save">
            {busy ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </Modal>
  );
};

export default ShareModal;
