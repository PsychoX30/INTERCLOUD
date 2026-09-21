import React, { useState, useEffect } from "react";
import { api } from "../../portal/api";
import Modal from "./Modal";
import { btnPrimary, btnSecondary, labelClass } from "../../pages/portal/ui";

const STAFF_ROLES = [
  { key: "admin", label: "Admin" },
  { key: "owner", label: "Owner" },
  { key: "sales", label: "Sales" },
  { key: "finance", label: "Finance" },
  { key: "support", label: "Support" },
  { key: "ticket_only", label: "Ticket" },
  { key: "creative", label: "Creative" },
];

const ShareModal = ({ doc, onClose, onSaved }) => {
  const [users, setUsers] = useState([]);
  const [selUsers, setSelUsers] = useState([]);
  const [selDivisions, setSelDivisions] = useState([]);
  const [selRoles, setSelRoles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    setSelUsers((doc.share_with?.users || []).map(String));
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

  const toggle = (setter) => (val) =>
    setter((p) => (p.includes(val) ? p.filter((x) => x !== val) : [...p, val]));

  const divisions = Array.from(new Set(users.map((u) => u.division).filter(Boolean)));

  const save = async () => {
    setBusy(true); setErr("");
    try {
      await api.patch(`/admin/documents/${doc.id}`, {
        share_with: { users: selUsers, divisions: selDivisions, roles: selRoles },
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
          <div className={labelClass}>User</div>
          <div className="max-h-44 overflow-y-auto border border-slate-200 rounded-xl p-2" data-testid="share-users">
            {users.length === 0 && <div className="text-xs text-slate-400">Tidak ada user / gagal memuat.</div>}
            {users.map((u) => (
              <label key={u.id} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-50 cursor-pointer text-sm">
                <input type="checkbox" checked={selUsers.includes(u.id)} onChange={() => toggle(setSelUsers)(u.id)} />
                <span className="flex-1 truncate">{u.name}{u.email ? ` · ${u.email}` : ""}</span>
              </label>
            ))}
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
