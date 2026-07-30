import React, { useEffect, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass, Loading, EmptyState } from "../ui";
import { Plus, Trash2, ArrowUp, ArrowDown, Eye, ExternalLink, Save, FormInput } from "lucide-react";
import { toast } from "sonner";

const FIELD_TYPES = [
  ["text", "Teks"], ["email", "Email"], ["phone", "Telepon"],
  ["textarea", "Teks panjang"], ["select", "Pilihan (dropdown)"],
  ["checkbox", "Checkbox"], ["number", "Angka"],
];

const AdminFormBuilder = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/admin/form-builder").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  const create = async () => {
    const name = window.prompt("Nama form baru:", "Form Kontak");
    if (!name) return;
    const r = await api.post("/admin/form-builder", { name });
    setEditing(r.data); load();
  };
  const del = async (f) => {
    if (!window.confirm(`Hapus form "${f.name}"?`)) return;
    await api.delete(`/admin/form-builder/${f.id}`); load();
  };

  if (rows === null) return <Loading />;
  return (
    <div data-testid="form-builder-page">
      <PageHeader title="Lead Form Builder" subtitle="Rancang form penangkap lead dengan field dinamis. Kiriman otomatis masuk ke Leads + CRM."
        action={<button className={btnPrimary} onClick={create} data-testid="fb-new-btn"><Plus className="h-4 w-4" /> Form baru</button>} />
      {rows.length === 0 && <EmptyState title="Belum ada form" subtitle="Buat form pertama untuk landing page Anda." />}
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {rows.map((f) => (
          <Card key={f.id} className="p-5" data-testid={`fb-card-${f.slug}`}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-extrabold text-[#0a2350]">{f.name}</div>
                <div className="text-xs text-slate-500 font-mono">/form/{f.slug}</div>
              </div>
              <StatusBadge status={f.active ? "active" : "inactive"} />
            </div>
            <div className="mt-3 text-xs text-slate-500">{f.fields.length} field · {f.submissions} kiriman</div>
            <div className="mt-4 flex gap-2 flex-wrap">
              <button className={btnSecondary} onClick={() => setEditing(f)} data-testid={`fb-edit-${f.slug}`}><FormInput className="h-4 w-4" /> Edit</button>
              <a className={btnSecondary} href={`/form/${f.slug}`} target="_blank" rel="noreferrer" data-testid={`fb-open-${f.slug}`}><ExternalLink className="h-4 w-4" /> Buka</a>
              <button className={`${btnSecondary} text-red-600`} onClick={() => del(f)} data-testid={`fb-del-${f.slug}`}><Trash2 className="h-4 w-4" /></button>
            </div>
          </Card>
        ))}
      </div>
      {editing && <FormEditor form={editing} onClose={() => { setEditing(null); load(); }} />}
    </div>
  );
};

const FormEditor = ({ form, onClose }) => {
  const [f, setF] = useState(form);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));
  const setField = (i, k, v) => setF((p) => {
    const fields = [...p.fields]; fields[i] = { ...fields[i], [k]: v }; return { ...p, fields };
  });
  const move = (i, dir) => setF((p) => {
    const fields = [...p.fields]; const j = i + dir;
    if (j < 0 || j >= fields.length) return p;
    [fields[i], fields[j]] = [fields[j], fields[i]];
    return { ...p, fields };
  });
  const addField = () => setF((p) => ({ ...p, fields: [...p.fields, { key: `field_${p.fields.length + 1}`, label: "Field baru", type: "text", required: false, placeholder: "", options: [] }] }));
  const delField = (i) => setF((p) => ({ ...p, fields: p.fields.filter((_, x) => x !== i) }));

  const save = async () => {
    setBusy(true);
    try {
      const fields = f.fields.map((x, i) => ({ ...x, order: i }));
      await api.put(`/admin/form-builder/${f.id}`, { ...f, fields });
      toast.success("Form disimpan");
      onClose();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menyimpan"); setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-5xl bg-white rounded-3xl overflow-hidden max-h-[92vh] flex flex-col" data-testid="fb-editor">
        <div className="p-5 bg-[#0a2350] text-white flex items-center justify-between">
          <div className="font-extrabold">{f.name} <span className="font-mono text-xs text-[#f5b120] ml-2">/form/{f.slug}</span></div>
          <label className="flex items-center gap-2 text-xs">
            <input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} data-testid="fb-active-toggle" /> Aktif
          </label>
        </div>
        <div className="flex-1 overflow-y-auto grid lg:grid-cols-2 gap-0">
          <div className="p-5 border-r border-slate-100 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <label><div className={labelClass}>Judul form</div>
                <input value={f.title} onChange={(e) => set("title", e.target.value)} className={inputClass} data-testid="fb-title" /></label>
              <label><div className={labelClass}>Label tombol</div>
                <input value={f.submit_label} onChange={(e) => set("submit_label", e.target.value)} className={inputClass} /></label>
            </div>
            <label className="block"><div className={labelClass}>Deskripsi</div>
              <input value={f.description} onChange={(e) => set("description", e.target.value)} className={inputClass} /></label>
            <label className="block"><div className={labelClass}>Pesan sukses</div>
              <input value={f.success_message} onChange={(e) => set("success_message", e.target.value)} className={inputClass} /></label>
            <div className="flex items-center justify-between">
              <div className="text-sm font-extrabold text-[#0a2350]">Fields</div>
              <button className={btnSecondary} onClick={addField} data-testid="fb-add-field"><Plus className="h-4 w-4" /> Tambah field</button>
            </div>
            <div className="space-y-3">
              {f.fields.map((fl, i) => (
                <div key={i} className="rounded-2xl border border-slate-200 p-3" data-testid={`fb-field-${i}`}>
                  <div className="flex items-center gap-2">
                    <input value={fl.label} onChange={(e) => setField(i, "label", e.target.value)} className={`${inputClass} h-8 text-sm font-semibold`} />
                    <button onClick={() => move(i, -1)} className="text-slate-400 hover:text-[#0a2350]" title="Naik" data-testid={`fb-up-${i}`}><ArrowUp className="h-4 w-4" /></button>
                    <button onClick={() => move(i, 1)} className="text-slate-400 hover:text-[#0a2350]" title="Turun" data-testid={`fb-down-${i}`}><ArrowDown className="h-4 w-4" /></button>
                    <button onClick={() => delField(i)} className="text-slate-400 hover:text-red-600" title="Hapus" data-testid={`fb-delfield-${i}`}><Trash2 className="h-4 w-4" /></button>
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    <select value={fl.type} onChange={(e) => setField(i, "type", e.target.value)} className={`${inputClass} h-8 text-xs`}>
                      {FIELD_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                    <input value={fl.key} onChange={(e) => setField(i, "key", e.target.value)} className={`${inputClass} h-8 text-xs font-mono`} placeholder="key" />
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input type="checkbox" checked={fl.required} onChange={(e) => setField(i, "required", e.target.checked)} /> Wajib
                    </label>
                  </div>
                  <input value={fl.placeholder} onChange={(e) => setField(i, "placeholder", e.target.value)} className={`${inputClass} h-8 text-xs mt-2`} placeholder="Placeholder (opsional)" />
                  {fl.type === "select" && (
                    <input value={(fl.options || []).join(", ")} onChange={(e) => setField(i, "options", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                      className={`${inputClass} h-8 text-xs mt-2`} placeholder="Opsi dipisah koma: A, B, C" />
                  )}
                </div>
              ))}
            </div>
          </div>
          <div className="p-5 bg-slate-50">
            <div className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-1"><Eye className="h-3.5 w-3.5" /> Preview live</div>
            <div className="bg-white rounded-2xl border border-slate-200 p-6" data-testid="fb-preview">
              <div className="text-xl font-extrabold text-[#0a2350]">{f.title}</div>
              {f.description && <p className="text-sm text-slate-500 mt-1">{f.description}</p>}
              <div className="mt-4 space-y-3">
                {f.fields.map((fl, i) => (
                  <div key={i}>
                    <div className={labelClass}>{fl.label}{fl.required && <span className="text-red-500"> *</span>}</div>
                    {fl.type === "textarea" ? <textarea rows={3} className={`${inputClass} h-auto py-2`} placeholder={fl.placeholder} disabled />
                      : fl.type === "select" ? (
                        <select className={inputClass} disabled>{(fl.options || []).map((o) => <option key={o}>{o}</option>)}</select>
                      ) : fl.type === "checkbox" ? <input type="checkbox" disabled />
                      : <input className={inputClass} placeholder={fl.placeholder} disabled />}
                  </div>
                ))}
                <button className={`${btnPrimary} w-full justify-center`} disabled>{f.submit_label}</button>
              </div>
            </div>
          </div>
        </div>
        <div className="p-4 border-t border-slate-100 flex justify-end gap-2">
          <button className={btnSecondary} onClick={onClose}>Batal</button>
          <button className={btnPrimary} onClick={save} disabled={busy} data-testid="fb-save"><Save className="h-4 w-4" /> Simpan form</button>
        </div>
      </div>
    </div>
  );
};

export default AdminFormBuilder;
