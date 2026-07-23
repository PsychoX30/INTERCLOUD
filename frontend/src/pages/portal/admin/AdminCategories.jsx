import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Plus, Edit, Trash2, Package as PackageIcon } from "lucide-react";
import { DataTable } from "../../../components/ui/data-table";

const AdminCategories = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/admin/categories").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  const del = async (id) => {
    if (!window.confirm("Delete this category?")) return;
    try { await api.delete(`/admin/categories/${id}`); load(); }
    catch (e) { alert(e?.response?.data?.detail || "Failed to delete"); }
  };

  const columns = [
    { key: "label", label: "Label / Slug", sortable: true,
      render: (_v, c) => (
        <>
          <div className="font-semibold text-[#0a2350]">{c.label}</div>
          <div className="text-[11px] text-slate-500 font-mono">{c.slug}</div>
        </>
      ) },
    { key: "description", label: "Description", sortable: false,
      render: (v) => <span className="text-slate-600">{v || "—"}</span> },
    { key: "sort_order", label: "Sort", sortable: true, align: "right",
      render: (v) => <span className="text-slate-600 tabular-nums">{v}</span> },
    { key: "product_count", label: "Products", sortable: true,
      render: (v) => (
        <span className="inline-flex items-center gap-1 text-xs font-bold text-[#0a2350] bg-slate-100 px-2 py-1 rounded">
          <PackageIcon className="h-3 w-3" /> {v}
        </span>
      ) },
    { key: "_actions", label: "Actions", sortable: false, align: "right",
      render: (_v, c) => (
        <span onClick={(e) => e.stopPropagation()} className="whitespace-nowrap">
          <button className="text-slate-600 hover:text-[#f5b120]" onClick={() => setEditing(c)} data-testid={`cat-edit-${c.slug}`}>
            <Edit className="h-4 w-4 inline" />
          </button>
          <button className="ml-3 text-slate-600 hover:text-red-600" onClick={() => del(c.id)} data-testid={`cat-del-${c.slug}`}>
            <Trash2 className="h-4 w-4 inline" />
          </button>
        </span>
      ) },
  ];

  return (
    <div>
      <PageHeader
        title="Product Categories"
        subtitle="Create custom categories to group products. Slug is what the API stores; label is what customers see."
        actions={<button onClick={() => setEditing("new")} data-testid="new-cat-btn" className={btnPrimary}><Plus className="h-4 w-4" /> Add category</button>}
      />

      <DataTable
        rows={rows || []}
        loading={rows === null}
        columns={columns}
        searchKeys={["label", "slug", "description"]}
        rowKey={(r) => r.id}
        empty={{ title: "No categories yet", hint: "Add your first product category." }}
        testid="admin-categories-table"
      />

      {editing && (
        <CategoryModal
          c={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
};

const CategoryModal = ({ c, onClose, onDone }) => {
  const [f, setF] = useState({
    slug: c?.slug || "",
    label: c?.label || "",
    description: c?.description || "",
    icon: c?.icon || "",
    sort_order: c?.sort_order ?? 100,
    is_active: c?.is_active ?? true,
  });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const isEdit = !!c;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      if (isEdit) await api.put(`/admin/categories/${c.id}`, f);
      else await api.post("/admin/categories", f);
      onDone();
    } catch (e2) {
      setErr(e2?.response?.data?.detail || "Failed to save");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-lg bg-white rounded-3xl p-6" data-testid="cat-modal">
        <h3 className="text-xl font-extrabold text-[#0a2350] mb-3">{isEdit ? "Edit category" : "New category"}</h3>
        {err && <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2 mb-3">{err}</div>}
        <div className="grid grid-cols-2 gap-3">
          <label><div className={labelClass}>Slug</div><input required value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} className={inputClass} data-testid="cat-slug" /></label>
          <label><div className={labelClass}>Label</div><input required value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} className={inputClass} data-testid="cat-label" /></label>
          <label className="col-span-2"><div className={labelClass}>Description</div><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className={inputClass} /></label>
          <label><div className={labelClass}>Icon (lucide-react name)</div><input value={f.icon} onChange={(e) => setF({ ...f, icon: e.target.value })} className={inputClass} placeholder="Server, Cloud, HardDrive…" /></label>
          <label><div className={labelClass}>Sort order</div><input type="number" value={f.sort_order} onChange={(e) => setF({ ...f, sort_order: Number(e.target.value) })} className={inputClass} /></label>
          <label className="col-span-2 flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} data-testid="cat-active" /> Show in public catalog
          </label>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary} data-testid="cat-submit">{isEdit ? "Save" : "Create"}</button>
        </div>
      </form>
    </div>
  );
};

export default AdminCategories;
