import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../../portal/api";
import { PageHeader, Card, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass, Loading, EmptyState } from "../ui";
import {
  Plus, Trash2, ArrowUp, ArrowDown, Eye, ExternalLink, Save, FormInput, Copy,
  Download, Send, Table2, Search, ChevronLeft, ChevronRight, X, Lock, Unlock, Link2,
} from "lucide-react";
import { toast } from "sonner";

// Mirrors _FB_FIELD_TYPES in backend/portal/routes/catalog.py. Keep in sync:
// a type accepted here that the backend rejects makes the save fail with 400.
const FIELD_TYPES = [
  ["text", "Teks"],
  ["textarea", "Teks panjang"],
  ["email", "Email"],
  ["phone", "Telepon"],
  ["number", "Angka"],
  ["url", "URL"],
  ["date", "Tanggal"],
  ["time", "Jam"],
  ["select", "Dropdown"],
  ["radio", "Pilihan (radio)"],
  ["multiselect", "Pilihan ganda"],
  ["checkbox", "Centang (ya/tidak)"],
  ["rating", "Rating"],
  ["section", "Judul bagian (layout)"],
];

const CHOICE_TYPES = new Set(["select", "radio", "multiselect"]);
const NUMERIC_TYPES = new Set(["number"]);
const TEXT_TYPES = new Set(["text", "textarea"]);

const AdminFormBuilder = () => {
  const [rows, setRows] = useState(null);
  const [editing, setEditing] = useState(null);
  const [viewing, setViewing] = useState(null);

  const load = useCallback(() => {
    return api.get("/admin/form-builder").then((r) => setRows(r.data));
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    const name = window.prompt("Nama form baru:", "Form Baru");
    if (!name) return;
    try {
      const r = await api.post("/admin/form-builder", { name });
      setEditing(r.data); load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal membuat form");
    }
  };
  const del = async (f) => {
    if (!window.confirm(`Hapus form "${f.name}" beserta ${f.submissions || 0} kirimannya?`)) return;
    try {
      await api.delete(`/admin/form-builder/${f.id}`); toast.success("Form dihapus"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };
  const publish = async (f) => {
    if (!window.confirm(`Publikasikan "${f.name}"? Setelah publish, form terkunci dan hanya bisa diubah lewat "Draft baru".`)) return;
    try {
      await api.put(`/admin/form-builder/${f.id}/publish`);
      toast.success("Form dipublikasikan"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal publish"); }
  };
  const newDraft = async (f) => {
    if (!window.confirm(`Buat draft baru dari "${f.name}"?`)) return;
    try {
      await api.put(`/admin/form-builder/${f.id}/draft`);
      toast.success("Draft baru dibuat"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal membuat draft"); }
  };
  const toggleClose = async (f) => {
    try {
      const r = await api.put(`/admin/form-builder/${f.id}/close`, { closed: !f.closed });
      toast.success(r.data.closed ? "Form ditutup" : "Form dibuka kembali"); load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal mengubah status"); }
  };
  const exportCsv = async (f) => {
    try {
      const res = await api.get(`/admin/form-builder/${f.id}/export`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url;
      a.download = `form-${f.slug}-v${f.version || 1}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch { toast.error("Gagal export CSV"); }
  };
  const shareUrl = (f) => `${window.location.origin}/form/${f.share_id || f.slug}`;
  const copyShare = async (f) => {
    try { await navigator.clipboard.writeText(shareUrl(f)); toast.success("Link share disalin"); }
    catch { window.prompt("Salin link ini:", shareUrl(f)); }
  };

  if (rows === null) return <Loading />;

  return (
    <div data-testid="form-builder-page">
      <PageHeader
        title="Form Builder"
        subtitle="Buat form sesuai kebutuhan, publikasikan, lalu bagikan link publiknya. Setiap form punya database kiriman sendiri yang bisa dilihat sebagai tabel dan diekspor ke CSV."
        actions={<button className={btnPrimary} onClick={create} data-testid="fb-new-btn"><Plus className="h-4 w-4" /> Form baru</button>}
      />
      {rows.length === 0 && (
        <EmptyState title="Belum ada form" body='Klik "Form baru" untuk membuat form pertama — misalnya form survei, undangan, atau daftar kehadiran.' />
      )}
      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {rows.map((f) => (
          <Card key={f.id} className="p-5" data-testid={`fb-card-${f.slug}`}>
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="font-extrabold text-[#0a2350] truncate">
                  {f.name} <span className="font-mono text-xs text-[#f5b120] ml-1">v{f.version || 1}</span>
                </div>
                <div className="text-xs text-slate-500 font-mono truncate">/form/{f.share_id || f.slug}</div>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <StatusBadge status={f.status === "published" ? (f.closed ? "closed" : "active") : "draft"} />
                {!f.active && <StatusBadge status="disabled" />}
              </div>
            </div>
            <div className="mt-3 text-xs text-slate-500">
              {f.fields.length} field · <span className="font-bold text-[#0a2350]">{f.submissions}</span> kiriman
              {f.submission_cap ? ` / kuota ${f.submission_cap}` : ""}
            </div>
            <div className="mt-4 flex gap-2 flex-wrap">
              <button className={btnSecondary} onClick={() => setEditing(f)} data-testid={`fb-edit-${f.slug}`}
                disabled={f.status === "published"} title={f.status === "published" ? "Form published terkunci — buat draft baru untuk mengedit" : "Edit form"}>
                <FormInput className="h-4 w-4" /> {f.status === "published" ? "Terkunci" : "Edit"}
              </button>
              <button className={btnSecondary} onClick={() => setViewing(f)} data-testid={`fb-data-${f.slug}`}>
                <Table2 className="h-4 w-4" /> Data
              </button>
              {f.status === "published" && (
                <a className={btnSecondary} href={`/form/${f.share_id || f.slug}`} target="_blank" rel="noreferrer" data-testid={`fb-open-${f.slug}`}>
                  <ExternalLink className="h-4 w-4" /> Buka
                </a>
              )}
              {f.status === "draft" && (
                <button className={btnPrimary} onClick={() => publish(f)} data-testid={`fb-publish-${f.slug}`}>
                  <Send className="h-4 w-4" /> Publikasikan
                </button>
              )}
              {f.status === "published" && (
                <>
                  <button className={btnSecondary} onClick={() => exportCsv(f)} data-testid={`fb-export-${f.slug}`}>
                    <Download className="h-4 w-4" /> CSV
                  </button>
                  <button className={btnSecondary} onClick={() => copyShare(f)} data-testid={`fb-copyshare-${f.slug}`}>
                    <Copy className="h-4 w-4" /> Salin link
                  </button>
                  <button className={btnSecondary} onClick={() => toggleClose(f)} data-testid={`fb-close-${f.slug}`}>
                    {f.closed ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />} {f.closed ? "Buka" : "Tutup"}
                  </button>
                  <button className={btnSecondary} onClick={() => newDraft(f)}>Draft baru</button>
                </>
              )}
              <button className={`${btnSecondary} !px-3 text-red-600`} onClick={() => del(f)} data-testid={`fb-del-${f.slug}`} title="Hapus form">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </Card>
        ))}
      </div>
      {editing && <FormEditor form={editing} onClose={() => { setEditing(null); load(); }} />}
      {viewing && <SubmissionsModal form={viewing} onClose={() => { setViewing(null); load(); }} />}
    </div>
  );
};

/* ------------------------------------------------------------------ editor */

const FormEditor = ({ form, onClose }) => {
  const [f, setF] = useState(form);
  const [busy, setBusy] = useState(false);
  const readonly = f.status === "published";
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
  const addField = (type = "text") => setF((p) => ({
    ...p,
    fields: [...p.fields, {
      key: `field_${p.fields.length + 1}`, label: "Field baru", type,
      required: false, placeholder: "", help: "", options: CHOICE_TYPES.has(type) ? ["Opsi 1", "Opsi 2"] : [],
      min: null, max: null, rating_max: 5, default: type === "multiselect" ? [] : type === "checkbox" ? false : "",
    }],
  }));
  const dupField = (i) => setF((p) => {
    const src = p.fields[i];
    const copy = { ...src, key: `${src.key}_${p.fields.length + 1}`, label: `${src.label} (copy)` };
    const fields = [...p.fields]; fields.splice(i + 1, 0, copy); return { ...p, fields };
  });
  const delField = (i) => setF((p) => ({ ...p, fields: p.fields.filter((_, x) => x !== i) }));

  const save = async () => {
    setBusy(true);
    try {
      const fields = f.fields.map((x, i) => ({ ...x, order: i }));
      await api.put(`/admin/form-builder/${f.id}`, { ...f, fields });
      toast.success("Form disimpan");
      onClose();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Gagal menyimpan"); setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-6xl bg-white rounded-3xl overflow-hidden max-h-[92vh] flex flex-col" data-testid="fb-editor">
        <div className="p-5 bg-[#0a2350] text-white flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="font-extrabold truncate">{f.name}</div>
            <div className="font-mono text-xs text-[#f5b120] truncate">/form/{f.share_id || f.slug} · v{f.version || 1} · {f.status}</div>
          </div>
          <label className="flex items-center gap-2 text-xs shrink-0">
            <input type="checkbox" checked={!!f.active} onChange={(e) => set("active", e.target.checked)}
              disabled={readonly} data-testid="fb-active-toggle" /> Aktif
          </label>
        </div>

        <div className="flex-1 overflow-y-auto grid lg:grid-cols-2">
          <div className="p-5 border-r border-slate-100 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <label><div className={labelClass}>Nama form</div>
                <input value={f.name} onChange={(e) => set("name", e.target.value)} className={inputClass} disabled={readonly} data-testid="fb-name" /></label>
              <label><div className={labelClass}>Judul tampil</div>
                <input value={f.title} onChange={(e) => set("title", e.target.value)} className={inputClass} disabled={readonly} data-testid="fb-title" /></label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label><div className={labelClass}>Deskripsi</div>
                <input value={f.description} onChange={(e) => set("description", e.target.value)} className={inputClass} disabled={readonly} /></label>
              <label><div className={labelClass}>Label tombol</div>
                <input value={f.submit_label} onChange={(e) => set("submit_label", e.target.value)} className={inputClass} disabled={readonly} /></label>
            </div>
            <label className="block"><div className={labelClass}>Pesan sukses</div>
              <input value={f.success_message} onChange={(e) => set("success_message", e.target.value)} className={inputClass} disabled={readonly} /></label>

            <div className="flex items-center justify-between pt-2">
              <div className="text-sm font-extrabold text-[#0a2350]">Fields ({f.fields.length})</div>
              {!readonly && (
                <button className={btnSecondary} onClick={() => addField("text")} data-testid="fb-add-field">
                  <Plus className="h-4 w-4" /> Tambah field
                </button>
              )}
            </div>

            <div className="space-y-3">
              {f.fields.map((fl, i) => (
                <div key={i} className="rounded-2xl border border-slate-200 p-3 bg-white" data-testid={`fb-field-${i}`}>
                  <div className="flex items-center gap-2">
                    <input value={fl.label} onChange={(e) => setField(i, "label", e.target.value)}
                      className={`${inputClass} h-9 text-sm font-semibold`} disabled={readonly} placeholder="Label field" />
                    {!readonly && (
                      <>
                        <button onClick={() => move(i, -1)} className="text-slate-400 hover:text-[#0a2350]" title="Naik" data-testid={`fb-up-${i}`}><ArrowUp className="h-4 w-4" /></button>
                        <button onClick={() => move(i, 1)} className="text-slate-400 hover:text-[#0a2350]" title="Turun" data-testid={`fb-down-${i}`}><ArrowDown className="h-4 w-4" /></button>
                        <button onClick={() => dupField(i)} className="text-slate-400 hover:text-[#0a2350]" title="Duplikat" data-testid={`fb-dup-${i}`}><Copy className="h-4 w-4" /></button>
                        <button onClick={() => delField(i)} className="text-slate-400 hover:text-red-600" title="Hapus" data-testid={`fb-delfield-${i}`}><Trash2 className="h-4 w-4" /></button>
                      </>
                    )}
                  </div>
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    <select value={fl.type} onChange={(e) => {
                      const t = e.target.value;
                      setField(i, "type", t);
                      if (CHOICE_TYPES.has(t) && (!fl.options || !fl.options.length))
                        setField(i, "options", ["Opsi 1", "Opsi 2"]);
                    }} className={`${inputClass} h-8 text-xs`} disabled={readonly} data-testid={`fb-type-${i}`}>
                      {FIELD_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                    <input value={fl.key} onChange={(e) => setField(i, "key", e.target.value)}
                      className={`${inputClass} h-8 text-xs font-mono`} placeholder="key" disabled={readonly} data-testid={`fb-key-${i}`} />
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input type="checkbox" checked={!!fl.required} onChange={(e) => setField(i, "required", e.target.checked)}
                        disabled={readonly} data-testid={`fb-req-${i}`} /> Wajib
                    </label>
                  </div>

                  {fl.type !== "section" && (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <input value={fl.placeholder || ""} onChange={(e) => setField(i, "placeholder", e.target.value)}
                        className={`${inputClass} h-8 text-xs`} placeholder="Placeholder" disabled={readonly} />
                      <input value={fl.help || ""} onChange={(e) => setField(i, "help", e.target.value)}
                        className={`${inputClass} h-8 text-xs`} placeholder="Teks bantuan (opsional)" disabled={readonly} />
                    </div>
                  )}

                  {CHOICE_TYPES.has(fl.type) && (
                    <input value={(fl.options || []).join(", ")}
                      onChange={(e) => setField(i, "options", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                      className={`${inputClass} h-8 text-xs mt-2`} placeholder="Opsi dipisah koma: A, B, C" disabled={readonly}
                      data-testid={`fb-options-${i}`} />
                  )}

                  {NUMERIC_TYPES.has(fl.type) && (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <input type="number" value={fl.min ?? ""} onChange={(e) => setField(i, "min", e.target.value === "" ? null : Number(e.target.value))}
                        className={`${inputClass} h-8 text-xs`} placeholder="Minimum" disabled={readonly} />
                      <input type="number" value={fl.max ?? ""} onChange={(e) => setField(i, "max", e.target.value === "" ? null : Number(e.target.value))}
                        className={`${inputClass} h-8 text-xs`} placeholder="Maksimum" disabled={readonly} />
                    </div>
                  )}

                  {fl.type === "rating" && (
                    <div className="mt-2">
                      <label className="text-[11px] text-slate-500">Skala maksimum
                        <input type="number" min={3} max={10} value={fl.rating_max || 5}
                          onChange={(e) => setField(i, "rating_max", Number(e.target.value))}
                          className={`${inputClass} h-8 text-xs mt-1`} disabled={readonly} />
                      </label>
                    </div>
                  )}

                  {TEXT_TYPES.has(fl.type) && (
                    <div className="mt-2">
                      <input type="number" value={fl.max ?? ""} onChange={(e) => setField(i, "max", e.target.value === "" ? null : Number(e.target.value))}
                        className={`${inputClass} h-8 text-xs`} placeholder="Maksimum karakter (opsional)" disabled={readonly} />
                    </div>
                  )}
                </div>
              ))}
              {f.fields.length === 0 && (
                <div className="text-center text-sm text-slate-400 py-6 border border-dashed border-slate-300 rounded-2xl">
                  Belum ada field. Tambahkan minimal satu.
                </div>
              )}
            </div>
          </div>

          <div className="p-5 bg-slate-50">
            <div className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-1">
              <Eye className="h-3.5 w-3.5" /> Preview
            </div>
            <div className="bg-white rounded-2xl border border-slate-200 p-6" data-testid="fb-preview">
              <div className="text-xl font-extrabold text-[#0a2350]">{f.title}</div>
              {f.description && <p className="text-sm text-slate-500 mt-1">{f.description}</p>}
              <div className="mt-4 space-y-3">
                {f.fields.map((fl, i) => (
                  <div key={i}>
                    {fl.type === "section" ? (
                      <div className="pt-3 border-t border-slate-200">
                        <div className="text-sm font-extrabold text-[#0a2350]">{fl.label}</div>
                        {fl.help && <p className="text-xs text-slate-500">{fl.help}</p>}
                      </div>
                    ) : (
                      <>
                        <div className={labelClass}>{fl.label}{fl.required && <span className="text-red-500"> *</span>}</div>
                        <PreviewInput field={fl} />
                      </>
                    )}
                  </div>
                ))}
                <button className={`${btnPrimary} w-full justify-center`} disabled>{f.submit_label}</button>
              </div>
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-slate-100 flex justify-between items-center gap-2">
          <div className="text-xs text-slate-400">
            {readonly ? "Form published terkunci. Gunakan Draft baru untuk mengubah." : "Perubahan tersimpan sebagai draft."}
          </div>
          <div className="flex gap-2">
            <button className={btnSecondary} onClick={onClose}>Batal</button>
            {!readonly && <button className={btnPrimary} onClick={save} disabled={busy} data-testid="fb-save"><Save className="h-4 w-4" /> Simpan form</button>}
          </div>
        </div>
      </div>
    </div>
  );
};

const PreviewInput = ({ field }) => {
  const cls = `${inputClass} pointer-events-none bg-slate-50`;
  switch (field.type) {
    case "textarea": return <textarea rows={2} className={cls} placeholder={field.placeholder} disabled />;
    case "select": return <select className={cls} disabled><option>Pilih...</option>{(field.options || []).map((o) => <option key={o}>{o}</option>)}</select>;
    case "radio":
    case "multiselect":
      return (
        <div className="space-y-1">
          {(field.options || []).map((o) => (
            <label key={o} className="flex items-center gap-2 text-xs text-slate-600">
              <input type={field.type === "radio" ? "radio" : "checkbox"} disabled /> {o}
            </label>
          ))}
        </div>
      );
    case "checkbox": return <label className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" disabled /> {field.placeholder || field.label}</label>;
    case "rating": return (
      <div className="flex gap-1">
        {Array.from({ length: field.rating_max || 5 }, (_, i) => (
          <span key={i} className="h-7 w-7 rounded border border-slate-300 text-[11px] grid place-items-center text-slate-400">{i + 1}</span>
        ))}
      </div>
    );
    case "date": return <input type="date" className={cls} disabled />;
    case "time": return <input type="time" className={cls} disabled />;
    case "number": return <input type="number" className={cls} placeholder={field.placeholder} disabled />;
    default: return <input type="text" className={cls} placeholder={field.placeholder} disabled />;
  }
};

/* -------------------------------------------------------- submissions view */

const PAGE_SIZE = 25;

const SubmissionsModal = ({ form, onClose }) => {
  const [data, setData] = useState(null);
  const [skip, setSkip] = useState(0);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [err, setErr] = useState("");

  const fetchPage = useCallback(() => {
    setErr("");
    const params = { skip, limit: PAGE_SIZE };
    if (query) params.q = query;
    if (status) params.status = status;
    return api.get(`/admin/form-builder/${form.id}/submissions`, { params })
      .then((r) => setData(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Gagal memuat data"));
  }, [form.id, skip, query, status]);

  useEffect(() => { fetchPage(); }, [fetchPage]);

  const delRow = async (row) => {
    if (!window.confirm("Hapus kiriman ini? Tindakan ini permanen.")) return;
    try {
      await api.delete(`/admin/form-builder/${form.id}/submissions/${row.id}`);
      toast.success("Kiriman dihapus"); fetchPage();
    } catch (e) { toast.error(e?.response?.data?.detail || "Gagal menghapus"); }
  };

  const exportFiltered = async () => {
    try {
      const params = {};
      if (query) params.q = query;
      if (status) params.status = status;
      const res = await api.get(`/admin/form-builder/${form.id}/export`, { params, responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a");
      a.href = url; a.download = `form-${form.slug}-v${form.version || 1}.csv`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
      toast.success("CSV diunduh");
    } catch { toast.error("Gagal export CSV"); }
  };

  const total = data?.total ?? 0;
  const cols = data?.columns || [];
  const rows = data?.rows || [];

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-[95vw] bg-white rounded-3xl overflow-hidden max-h-[92vh] flex flex-col" data-testid="fb-submissions">
        <div className="p-5 bg-[#0a2350] text-white flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-extrabold truncate">Database · {form.name}</div>
            <div className="text-xs text-slate-300 font-mono truncate">
              <Link2 className="inline h-3 w-3 mr-1" />
              {`${window.location.origin}/form/${form.share_id || form.slug}`}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button className="inline-flex items-center gap-1.5 rounded-lg bg-[#f5b120] text-[#0a2350] text-sm font-semibold px-3 h-9 hover:brightness-95"
              onClick={exportFiltered} data-testid="fb-data-export">
              <Download className="h-4 w-4" /> Export CSV
            </button>
            <button className="text-white/70 hover:text-white" onClick={onClose} data-testid="fb-data-close" aria-label="Tutup">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="p-4 border-b border-slate-100 flex flex-wrap items-center gap-2">
          <form onSubmit={(e) => { e.preventDefault(); setSkip(0); setQuery(q.trim()); }} className="flex gap-2 flex-1 min-w-[240px]">
            <div className="relative flex-1">
              <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama, email, atau jawaban..."
                className={`${inputClass} pl-9`} data-testid="fb-data-search" />
            </div>
            <button type="submit" className={btnSecondary} data-testid="fb-data-search-btn">Cari</button>
            {(query || status) && (
              <button type="button" className={btnSecondary} onClick={() => { setQ(""); setQuery(""); setStatus(""); setSkip(0); }}>
                Reset
              </button>
            )}
          </form>
          <select value={status} onChange={(e) => { setStatus(e.target.value); setSkip(0); }}
            className={`${inputClass} max-w-[200px]`} data-testid="fb-data-status">
            <option value="">Semua kiriman</option>
            <option value="with_email">Hanya yang punya email</option>
            <option value="without_email">Tanpa email</option>
          </select>
          <div className="text-xs text-slate-500 ml-auto">
            <span className="font-bold text-[#0a2350]">{total}</span> kiriman
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          {err && <div className="p-4 text-sm text-red-600">{err}</div>}
          {!data && !err && <Loading />}
          {data && rows.length === 0 && (
            <EmptyState title="Belum ada kiriman" body="Bagikan link form untuk mulai menerima data." />
          )}
          {data && rows.length > 0 && (
            <table className="w-full text-sm border-collapse" data-testid="fb-data-table">
              <thead className="sticky top-0 bg-slate-50 z-10">
                <tr>
                  <th className="text-left px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-500 border-b border-slate-200 whitespace-nowrap">#</th>
                  {cols.map((c) => (
                    <th key={c.key} className="text-left px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-500 border-b border-slate-200 whitespace-nowrap">
                      {c.label}
                    </th>
                  ))}
                  <th className="border-b border-slate-200" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={r.id} className="hover:bg-slate-50/70" data-testid={`fb-row-${i}`}>
                    <td className="px-3 py-2 text-xs text-slate-400 border-b border-slate-100">{skip + i + 1}</td>
                    {cols.map((c) => (
                      <td key={c.key} className="px-3 py-2 border-b border-slate-100 align-top">
                        <CellValue col={c} value={(r.values || {})[c.key]} />
                      </td>
                    ))}
                    <td className="px-3 py-2 border-b border-slate-100 text-right">
                      <button onClick={() => delRow(r)} className="text-slate-300 hover:text-red-600" title="Hapus kiriman">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="p-3 border-t border-slate-100 flex items-center justify-between gap-2">
          <div className="text-xs text-slate-500">
            {total === 0 ? "0" : `${skip + 1}–${Math.min(skip + PAGE_SIZE, total)}`} dari {total}
          </div>
          <div className="flex gap-2">
            <button className={btnSecondary} disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - PAGE_SIZE))}
              data-testid="fb-data-prev"><ChevronLeft className="h-4 w-4" /> Sebelumnya</button>
            <button className={btnSecondary} disabled={skip + PAGE_SIZE >= total} onClick={() => setSkip(skip + PAGE_SIZE)}
              data-testid="fb-data-next">Berikutnya <ChevronRight className="h-4 w-4" /></button>
          </div>
        </div>
      </div>
    </div>
  );
};

const CellValue = ({ col, value }) => {
  if (value === undefined || value === null || value === "") return <span className="text-slate-300">—</span>;
  if (col.type === "datetime") {
    const s = String(value);
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return <span className="text-xs text-slate-600 whitespace-nowrap" title={s}>{d.toLocaleString("id-ID")}</span>;
    }
    return <span className="text-xs text-slate-600">{s}</span>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-slate-300">—</span>;
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((v) => (
          <span key={v} className="inline-block rounded bg-[#f5b120]/20 text-[#0a2350] text-[11px] px-1.5 py-0.5 font-medium">{String(v)}</span>
        ))}
      </div>
    );
  }
  if (typeof value === "boolean") {
    return <span className={value ? "text-emerald-600" : "text-slate-400"}>{value ? "Ya" : "Tidak"}</span>;
  }
  if (col.type === "date" || col.type === "time") {
    return <span className="whitespace-nowrap text-slate-700">{String(value)}</span>;
  }
  const s = String(value);
  return <span className="text-slate-700" title={s.length > 80 ? s : undefined}>{s.length > 120 ? `${s.slice(0, 120)}…` : s}</span>;
};

export default AdminFormBuilder;
