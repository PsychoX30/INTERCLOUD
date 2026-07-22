import React, { useEffect, useState } from "react";
import { api, shortDate } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { UserPlus, Users, ShieldCheck, Edit, KeyRound } from "lucide-react";

const AdminUsers = () => {
  const [rows, setRows] = useState(null);
  const [modal, setModal] = useState(false);
  const [accessUser, setAccessUser] = useState(null);
  const [resetUser, setResetUser] = useState(null);
  const [clients, setClients] = useState([]);
  const [catalog, setCatalog] = useState(null);

  const load = () => api.get("/admin/users").then((r) => {
    setRows(r.data);
    setClients(r.data.filter((u) => u.role === "client"));
  });
  useEffect(() => {
    load();
    api.get("/admin/user-access-catalog").then((r) => setCatalog(r.data)).catch(() => {});
  }, []);

  if (!rows) return <Loading />;
  return (
    <div>
      <PageHeader
        title="Users & Clients"
        subtitle="Register new users, assign roles & menu access, and pick which clients each staff member handles."
        actions={<button className={btnPrimary} onClick={() => setModal(true)} data-testid="new-user-btn"><UserPlus className="h-4 w-4" /> New user</button>}
      />
      {rows.length === 0 && <EmptyState title="No users yet" />}
      <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">Name</th>
              <th className="px-4 py-3 text-left">Email</th>
              <th className="px-4 py-3 text-left">Company</th>
              <th className="px-4 py-3 text-left">Role</th>
              <th className="px-4 py-3 text-left">Access</th>
              <th className="px-4 py-3 text-left">Since</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((u) => (
              <tr key={u.id} className="border-t border-slate-100" data-testid={`user-${u.email}`}>
                <td className="px-4 py-3 font-semibold text-[#0a2350]">{u.name}</td>
                <td className="px-4 py-3 text-slate-600">{u.email}</td>
                <td className="px-4 py-3 text-slate-600">{u.company || "-"}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide ${u.role === "admin" ? "bg-[#f5b120]/20 text-[#0a2350]" : u.role === "client" ? "bg-emerald-100 text-emerald-700" : "bg-sky-100 text-sky-700"}`}>{u.role}</span>
                </td>
                <td className="px-4 py-3 text-xs text-slate-600">
                  {u.role === "client" ? (
                    <span className="text-slate-400">—</span>
                  ) : (
                    <div className="flex flex-col gap-0.5">
                      {u.menu_keys && u.menu_keys.length > 0
                        ? <span className="font-semibold">{u.menu_keys.length} menu(s)</span>
                        : <span className="text-slate-500">Default for {u.role}</span>}
                      {u.assigned_client_ids?.length > 0 && (
                        <span className="text-emerald-600 text-[10px]">{u.assigned_client_ids.length} client(s) assigned</span>
                      )}
                      {u.feature_flags?.length > 0 && (
                        <span className="text-purple-600 text-[10px]">{u.feature_flags.length} feature flag(s)</span>
                      )}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-500 text-xs">{shortDate(u.created_at)}</td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => setResetUser(u)}
                    className="text-slate-600 hover:text-red-600 font-bold text-xs inline-flex items-center gap-1 mr-3"
                    data-testid={`reset-pw-${u.email}`}
                    title="Reset password"
                  >
                    <KeyRound className="h-3.5 w-3.5" /> Reset pw
                  </button>
                  {u.role !== "client" && catalog && (
                    <button
                      onClick={() => setAccessUser(u)}
                      className="text-[#0a2350] hover:text-[#f5b120] font-bold text-xs inline-flex items-center gap-1"
                      data-testid={`edit-access-${u.email}`}
                    >
                      <ShieldCheck className="h-3.5 w-3.5" /> Manage access
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {modal && <NewUserModal onClose={() => setModal(false)} onDone={() => { setModal(false); load(); }} />}
      {accessUser && catalog && (
        <UserAccessModal
          user={accessUser}
          catalog={catalog}
          clients={clients}
          onClose={() => setAccessUser(null)}
          onDone={() => { setAccessUser(null); load(); }}
        />
      )}
      {resetUser && (
        <AdminResetPasswordModal
          user={resetUser}
          onClose={() => setResetUser(null)}
          onDone={() => { setResetUser(null); load(); }}
        />
      )}
    </div>
  );
};

/* ==== Admin reset-password modal (sets a new password for another user) ==== */
const AdminResetPasswordModal = ({ user, onClose, onDone }) => {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [notify, setNotify] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (pw.length < 8) return setErr("Password must be at least 8 characters.");
    if (pw !== pw2) return setErr("Password confirmation does not match.");
    if (!window.confirm(`Reset password for ${user.email}? This will invalidate all existing reset links for this user.`)) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/admin/users/${user.id}/reset-password`, { new_password: pw, notify_user: notify });
      setResult(data);
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Failed to reset");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-md bg-white rounded-3xl p-6" data-testid="admin-reset-modal">
        <h3 className="text-xl font-extrabold text-[#0a2350]">Reset password</h3>
        <div className="text-sm text-slate-500 mt-0.5">Set a new password for <b className="text-[#0a2350]">{user.name}</b> ({user.email}).</div>
        {result ? (
          <div className="mt-5 text-sm bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl px-3 py-3">
            <div className="font-bold">Done.</div>
            <div className="mt-1">{result.message}</div>
            {notify && (<div className="mt-1 text-xs">Notification email: {result.email_sent ? "sent" : "NOT sent (SMTP integration is disabled)"}.</div>)}
            <div className="mt-3"><button onClick={onDone} className={btnPrimary}>Close</button></div>
          </div>
        ) : (
          <form onSubmit={submit} className="mt-5 space-y-3">
            {err && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
            <label className="block">
              <div className={labelClass}>New password</div>
              <input type="password" required minLength={8} value={pw} onChange={(e) => setPw(e.target.value)}
                     className={`${inputClass} mt-1`} data-testid="admin-reset-new" />
            </label>
            <label className="block">
              <div className={labelClass}>Confirm password</div>
              <input type="password" required minLength={8} value={pw2} onChange={(e) => setPw2(e.target.value)}
                     className={`${inputClass} mt-1`} data-testid="admin-reset-confirm" />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} data-testid="admin-reset-notify" />
              <span className="text-slate-600">Send the user an email notification</span>
            </label>
            <div className="pt-2 flex justify-end gap-2">
              <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
              <button type="submit" disabled={busy} className={btnPrimary} data-testid="admin-reset-submit">
                {busy ? "Resetting…" : "Reset password"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

/* ==== User access modal — menu permissions + feature flags + client assignments ==== */
const UserAccessModal = ({ user, catalog, clients, onClose, onDone }) => {
  const [menuKeys, setMenuKeys] = useState(user.menu_keys || []);
  const [flags, setFlags] = useState(user.feature_flags || []);
  const [assigned, setAssigned] = useState(user.assigned_client_ids || []);
  const [useDefault, setUseDefault] = useState(!user.menu_keys || user.menu_keys.length === 0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const toggleMenu = (k) => {
    setMenuKeys((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]);
    setUseDefault(false);
  };
  const toggleFlag = (k) => setFlags((prev) => prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]);
  const toggleClient = (id) => setAssigned((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);

  const save = async () => {
    setBusy(true); setErr("");
    try {
      await api.put(`/admin/users/${user.id}`, {
        menu_keys: useDefault ? [] : menuKeys,
        feature_flags: flags,
        assigned_client_ids: assigned,
      });
      onDone();
    } catch (e) {
      setErr(e?.response?.data?.detail || "Failed to save");
    } finally { setBusy(false); }
  };

  // Group menu catalog for display
  const groups = {};
  for (const m of catalog.menu_catalog) {
    (groups[m.group] ??= []).push(m);
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-3xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="user-access-modal">
        <h3 className="text-xl font-extrabold text-[#0a2350]">Access for {user.name}</h3>
        <div className="text-sm text-slate-500">{user.email} · <b className="uppercase">{user.role}</b></div>
        {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}

        {/* Menu access */}
        <div className="mt-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350]">Menu access</div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={useDefault} onChange={(e) => setUseDefault(e.target.checked)} data-testid="use-default-menus" />
              <span className="text-slate-600">Use default for role <b className="uppercase text-slate-800">{user.role}</b></span>
            </label>
          </div>
          {!useDefault && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(groups).map(([grpLabel, items]) => (
                <div key={grpLabel} className="border border-slate-200 rounded-xl p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 mb-1">{grpLabel}</div>
                  {items.map((m) => {
                    const on = menuKeys.includes(m.key);
                    const roleDefault = m.default_roles.includes(user.role);
                    return (
                      <label key={m.key} className="flex items-center gap-2 text-sm py-1" data-testid={`menu-${m.key}`}>
                        <input type="checkbox" checked={on} onChange={() => toggleMenu(m.key)} />
                        <span className="text-slate-700">{m.label}</span>
                        {roleDefault && <span className="text-[10px] text-emerald-600 font-bold">default</span>}
                      </label>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
          {useDefault && (
            <div className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
              This user sees the standard menus for role <b className="uppercase">{user.role}</b>. Uncheck the box above to customize.
            </div>
          )}
        </div>

        {/* Feature flags */}
        <div className="mt-5">
          <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350] mb-2">Feature flags</div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-1 border border-slate-200 rounded-xl p-3">
            {catalog.feature_flags.map((ff) => (
              <label key={ff.key} className="flex items-center gap-2 text-sm py-1" data-testid={`flag-${ff.key}`}>
                <input type="checkbox" checked={flags.includes(ff.key)} onChange={() => toggleFlag(ff.key)} />
                <span className="text-slate-700">{ff.label}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Assigned clients (sales/support only) */}
        {(user.role === "sales" || user.role === "support") && (
          <div className="mt-5">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350]">Assigned clients</div>
              <div className="text-xs text-slate-500">{assigned.length} of {clients.length}</div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-1 max-h-56 overflow-y-auto border border-slate-200 rounded-xl p-3">
              {clients.map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-sm py-1">
                  <input type="checkbox" checked={assigned.includes(c.id)} onChange={() => toggleClient(c.id)} />
                  <span className="text-slate-700 truncate">{c.name} · <span className="text-slate-500">{c.email}</span></span>
                </label>
              ))}
            </div>
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={save} disabled={busy} className={btnPrimary} data-testid="save-access">Save access</button>
        </div>
      </div>
    </div>
  );
};

const NewUserModal = ({ onClose, onDone }) => {
  const [f, setF] = useState({
    email: "", password: "", name: "", role: "client", company: "", phone: "",
    attention: "", address_line1: "", address_line2: "", city: "", province: "",
    postal_code: "", country: "Indonesia", npwp: "",
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      await api.post("/admin/users", f);
      onDone();
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed to create user");
    } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-2xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="new-user-form">
        <h3 className="text-xl font-extrabold text-[#0a2350]">Register a new user</h3>
        {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <F label="Name" onChange={(v) => setF({ ...f, name: v })} val={f.name} testid="u-name" full />
          <F label="Email" type="email" onChange={(v) => setF({ ...f, email: v })} val={f.email} testid="u-email" full />
          <F label="Password" type="password" onChange={(v) => setF({ ...f, password: v })} val={f.password} testid="u-password" />
          <div>
            <div className={labelClass}>Role</div>
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} className={inputClass} data-testid="u-role">
              <option value="client">Client</option>
              <option value="admin">Admin</option>
              <option value="sales">Sales</option>
              <option value="support">Support</option>
              <option value="ticket_only">Ticket only</option>
            </select>
          </div>
          <F label="Company" onChange={(v) => setF({ ...f, company: v })} val={f.company} testid="u-company" />
          <F label="Phone" onChange={(v) => setF({ ...f, phone: v })} val={f.phone} testid="u-phone" />
        </div>

        <div className="mt-6">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-500 mb-2">Billing address (used on invoices &amp; quotations)</div>
          <div className="grid grid-cols-2 gap-3">
            <F label="ATTN (person to address)" onChange={(v) => setF({ ...f, attention: v })} val={f.attention} testid="u-attn" full />
            <F label="Address line 1" onChange={(v) => setF({ ...f, address_line1: v })} val={f.address_line1} testid="u-addr1" full />
            <F label="Address line 2" onChange={(v) => setF({ ...f, address_line2: v })} val={f.address_line2} testid="u-addr2" full />
            <F label="City" onChange={(v) => setF({ ...f, city: v })} val={f.city} testid="u-city" />
            <F label="Province / State" onChange={(v) => setF({ ...f, province: v })} val={f.province} testid="u-province" />
            <F label="Postal code" onChange={(v) => setF({ ...f, postal_code: v })} val={f.postal_code} testid="u-postal" />
            <F label="Country" onChange={(v) => setF({ ...f, country: v })} val={f.country} testid="u-country" />
            <F label="NPWP (tax ID)" onChange={(v) => setF({ ...f, npwp: v })} val={f.npwp} testid="u-npwp" full />
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary} data-testid="u-submit">Create</button>
        </div>
      </form>
    </div>
  );
};

export const F = ({ label, val, onChange, type = "text", full, testid, required }) => (
  <label className={full ? "col-span-2" : ""}>
    <div className={labelClass}>{label}{required && " *"}</div>
    <input type={type} value={val} onChange={(e) => onChange(e.target.value)} className={inputClass} data-testid={testid} required={required} />
  </label>
);

export default AdminUsers;
