import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, money } from "../../../portal/api";
import { PageHeader, Loading, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Edit, Trash2, Plus, ChevronDown, ChevronUp, X, Puzzle, Package } from "lucide-react";
import { DataTable } from "../../../components/ui/data-table";
import TablePager from "./TablePager";

/* ---------------------------------------------------------------
   Admin Products page - WHMCS-style catalog editor
   • Categories load from /admin/categories (dynamic)
   • Option groups: dropdown / checkbox / quantity, with per-option
     monthly/setup deltas and defaults
   • Add-ons: is_addon flag + applies_to_categories / product_ids
   --------------------------------------------------------------- */

// Ringkasan spec provisioning: "1 vCPU · 1 GB RAM · 20 GB" (add-on: prefiks +)
const specText = (p) => {
  const pr = p.provision || {};
  const pre = p.is_addon ? "+" : "";
  const parts = [];
  if (Number(pr.cores)) parts.push(`${pre}${Number(pr.cores)} vCPU`);
  if (Number(pr.memory_mb)) parts.push(`${pre}${+(Number(pr.memory_mb) / 1024).toFixed(1)} GB RAM`);
  if (Number(pr.disk_gb)) parts.push(`${pre}${Number(pr.disk_gb)} GB`);
  if (p.is_addon && Number(pr.ip)) parts.push(`+${Number(pr.ip)} IP`);
  return parts.join(" · ");
};

const AdminProducts = () => {
  const location = useLocation();
  const initialFilter = location.pathname.endsWith("/addons") ? "addons" : "all";
  const [rows, setRows] = useState(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [limit, setLimit] = useState(50);
  const [cats, setCats] = useState([]);
  const [editing, setEditing] = useState(null);
  const [filter, setFilter] = useState(initialFilter); // all | base | addons

  const params = useMemo(() => ({
    paginate: true,
    skip: page * limit,
    limit,
    ...(filter === "addons" ? { is_addon: true } : filter === "base" ? { is_addon: false } : {}),
  }), [filter, page, limit]);

  const loadProducts = useCallback(() => {
    api.get("/admin/products", { params }).then((r) => {
      setRows(r.data?.items || []);
      setTotal(r.data?.total || 0);
    });
  }, [params]);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  const load = useCallback(() => {
    api.get("/admin/categories").then((c) => setCats(c.data)).catch(() => {});
    loadProducts();
  }, [loadProducts]);

  useEffect(() => {
    setFilter(location.pathname.endsWith("/addons") ? "addons" : "all");
  }, [location.pathname]);

  useEffect(() => {
    api.get("/admin/categories").then((c) => setCats(c.data)).catch(() => {});
  }, []);

  if (!rows) return <Loading />;

  return (
    <div>
      <PageHeader
        title="Products & Services"
        subtitle="Base plans, add-ons, and per-plan configurable options - visible to clients during the order flow."
        actions={<button className={btnPrimary} onClick={() => setEditing("new")} data-testid="new-product-btn"><Plus className="h-4 w-4" /> New product</button>}
      />

      <div className="flex gap-2 mb-3">
        {["all", "base", "addons"].map((f) => (
          <button
            key={f}
            onClick={() => { setPage(0); setFilter(f); }}
            data-testid={`filter-${f}`}
            className={`h-8 px-3 rounded-full text-xs font-bold uppercase tracking-widest ${
              filter === f ? "bg-[#0a2350] text-white" : "bg-white text-slate-500 border border-slate-200"
            }`}
          >
            {f === "all" ? `All (${total})` : f === "base" ? `Base plans` : `Add-ons`}
          </button>
        ))}
      </div>

      <DataTable
        rows={rows}
        loading={false}
        columns={[
          { key: "name", label: "Name", sortable: true,
            render: (_v, p) => (
              <>
                <div className="font-semibold text-[#0a2350]">{p.name}</div>
                <div className="text-xs text-slate-500 line-clamp-1">{p.description}</div>
              </>
            ) },
          { key: "category", label: "Category", sortable: true,
            render: (v) => <span className="uppercase text-xs font-bold text-[#f5b120]">{v}</span> },
          { key: "is_addon", label: "Type", sortable: true,
            render: (v) => v ? (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase bg-purple-100 text-purple-700 px-2 py-0.5 rounded"><Puzzle className="h-3 w-3" /> Add-on</span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase bg-slate-100 text-slate-700 px-2 py-0.5 rounded"><Package className="h-3 w-3" /> Base</span>
            ) },
          { key: "provision", label: "Spec", sortable: false,
            render: (_v, p) => {
              const s = specText(p);
              return s ? <span className="text-xs font-semibold text-[#0a2350] whitespace-nowrap" data-testid={`product-spec-${p.id}`}>{s}</span> : <span className="text-xs text-slate-400">-</span>;
            } },
          { key: "option_groups", label: "Options", sortable: false,
            render: (v) => <span className="text-xs text-slate-500">{(v || []).length > 0 ? `${v.length} groups` : "-"}</span> },
          { key: "price_monthly", label: "Monthly", sortable: true, align: "right",
            render: (v) => <span className="font-semibold">{v ? money(v) : "-"}</span> },
          { key: "setup_fee", label: "Setup", sortable: true, align: "right",
            render: (v) => v ? money(v) : "-" },
          { key: "is_active", label: "Status", sortable: true,
            render: (v) => <StatusBadge status={v ? "enabled" : "disabled"} /> },
          { key: "_actions", label: "Actions", sortable: false, align: "right",
            render: (_v, p) => (
              <span onClick={(e) => e.stopPropagation()} className="whitespace-nowrap">
                <button onClick={() => setEditing(p)} className="text-slate-600 hover:text-[#f5b120]" data-testid={`product-edit-${p.id}`}>
                  <Edit className="h-4 w-4 inline" />
                </button>
                <button
                  onClick={async () => {
                    if (window.confirm(`Delete "${p.name}"?`)) { await api.delete(`/admin/products/${p.id}`); load(); }
                  }}
                  className="text-slate-600 hover:text-red-600 ml-3"
                  data-testid={`product-del-${p.id}`}
                >
                  <Trash2 className="h-4 w-4 inline" />
                </button>
              </span>
            ) },
        ]}
        searchKeys={["name", "category", "description"]}
        rowKey={(r) => r.id}
        empty={{ title: "No products in this view", hint: "Create products or add-ons to sell." }}
        testid="admin-products-table"
      />

      {rows !== null && total > 0 && (
        <TablePager
          page={page}
          total={total}
          limit={limit}
          onPage={setPage}
          onLimit={(l) => {
            setLimit(l);
            setPage(0);
          }}
          testid="admin-products-pager"
        />
      )}

      {editing && (
        <ProductForm
          p={editing === "new" ? null : editing}
          categories={cats}
          allProducts={rows}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
};

/* ============ Product form (with option-group editor) ============ */
const emptyOption = () => ({ label: "", price_monthly_delta: 0, price_setup_delta: 0, is_default: false });
const emptyGroup = () => ({
  key: "", label: "", type: "dropdown", required: true, options: [emptyOption()],
  min_qty: 0, max_qty: 10, step_qty: 1, unit_label: "", unit_price_monthly: 0, unit_price_setup: 0,
});

const ProductForm = ({ p, categories, allProducts, onClose, onDone }) => {
  const [f, setF] = useState({
    name: p?.name || "",
    category: p?.category || (categories[0]?.slug || "vps"),
    description: p?.description || "",
    price_monthly: p?.price_monthly || 0,
    setup_fee: p?.setup_fee || 0,
    billing_cycle: p?.billing_cycle || "monthly",
    features: (p?.features || []).join("\n"),
    is_active: p?.is_active !== false,
    is_addon: !!p?.is_addon,
    applies_to_categories: p?.applies_to_categories || [],
    applies_to_product_ids: p?.applies_to_product_ids || [],
    option_groups: p?.option_groups || [],
    provision: {
      ...(p?.provision || {}),
      ram_gb: p?.provision?.memory_mb ? +(p.provision.memory_mb / 1024).toFixed(1) : "",
    },
    sort_order: p?.sort_order ?? 100,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    const payload = {
      name: f.name,
      category: f.category,
      description: f.description,
      price_monthly: Number(f.price_monthly) || 0,
      setup_fee: Number(f.setup_fee) || 0,
      billing_cycle: f.billing_cycle,
      features: f.features.split("\n").map((s) => s.trim()).filter(Boolean),
      is_active: !!f.is_active,
      is_addon: !!f.is_addon,
      applies_to_categories: f.applies_to_categories,
      applies_to_product_ids: f.applies_to_product_ids,
      option_groups: f.is_addon ? [] : f.option_groups,
      provision: f.is_addon ? {
        cores: Number(f.provision?.cores) || 0,
        memory_mb: Number(f.provision?.memory_mb) || 0,
        disk_gb: Number(f.provision?.disk_gb) || 0,
        ip: Number(f.provision?.ip) || 0,
      } : ["vps", "cloud"].includes(f.category) ? {
        template_vmid: Number(f.provision?.template_vmid) || null,
        cores: Number(f.provision?.cores) || null,
        memory_mb: Math.round((Number(f.provision?.ram_gb) || 0) * 1024) || null,
        disk_gb: Number(f.provision?.disk_gb) || null,
      } : {},
      sort_order: Number(f.sort_order) || 100,
    };
    try {
      if (p) await api.put(`/admin/products/${p.id}`, payload);
      else await api.post("/admin/products", payload);
      onDone();
    } catch (er) {
      setErr(er?.response?.data?.detail || "Failed to save");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <form onSubmit={submit} onClick={(e) => e.stopPropagation()} className="w-full max-w-3xl bg-white rounded-3xl p-6 max-h-[92vh] overflow-y-auto" data-testid="product-form">
        <h3 className="text-xl font-extrabold text-[#0a2350]">{p ? "Edit product" : "New product"}</h3>
        {err && <div className="mt-3 text-sm text-red-700 bg-red-50 border border-red-200 rounded px-3 py-2">{err}</div>}

        {/* ---------- Basic ---------- */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="col-span-2 flex items-center gap-2 bg-purple-50 border border-purple-200 rounded-xl p-3">
            <input type="checkbox" checked={f.is_addon} onChange={(e) => setF({ ...f, is_addon: e.target.checked })} data-testid="p-is-addon" />
            <div>
              <div className="font-bold text-purple-800 text-sm">This is an <b>add-on</b>, not a base product</div>
              <div className="text-xs text-purple-700">Add-ons attach to a base product during the client order flow.</div>
            </div>
          </label>

          <label className="col-span-2"><div className={labelClass}>Name *</div><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} className={inputClass} data-testid="p-name" /></label>

          <label><div className={labelClass}>Category</div>
            <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} className={inputClass} data-testid="p-cat">
              {categories.map((c) => <option key={c.slug} value={c.slug}>{c.label} ({c.slug})</option>)}
            </select>
          </label>
          <label><div className={labelClass}>Billing cycle</div>
            <select value={f.billing_cycle} onChange={(e) => setF({ ...f, billing_cycle: e.target.value })} className={inputClass}>
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="semiannual">Semi-annual</option>
              <option value="annual">Annual</option>
            </select>
          </label>

          <label><div className={labelClass}>Monthly (IDR)</div><input type="number" value={f.price_monthly} onChange={(e) => setF({ ...f, price_monthly: e.target.value })} className={inputClass} data-testid="p-price" /></label>
          <label><div className={labelClass}>Setup fee (IDR)</div><input type="number" value={f.setup_fee} onChange={(e) => setF({ ...f, setup_fee: e.target.value })} className={inputClass} /></label>

          <label><div className={labelClass}>Sort order</div><input type="number" value={f.sort_order} onChange={(e) => setF({ ...f, sort_order: e.target.value })} className={inputClass} /></label>
          <label><div className={labelClass}>Status</div>
            <select value={f.is_active ? "y" : "n"} onChange={(e) => setF({ ...f, is_active: e.target.value === "y" })} className={inputClass}>
              <option value="y">Enabled - visible to clients</option>
              <option value="n">Disabled - hidden</option>
            </select>
          </label>

          <label className="col-span-2"><div className={labelClass}>Description</div><textarea rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
          <label className="col-span-2"><div className={labelClass}>Features (one per line)</div><textarea rows={4} value={f.features} onChange={(e) => setF({ ...f, features: e.target.value })} className={`${inputClass} h-auto py-2 font-mono text-xs`} /></label>
        </div>

        {/* ---------- Base VM spec (VPS / Cloud plans) ---------- */}
        {!f.is_addon && ["vps", "cloud"].includes(f.category) && (
          <div className="mt-5 border-t border-slate-200 pt-5" data-testid="base-spec-fields">
            <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350] mb-1">Spesifikasi Dasar VM (auto-provisioning)</div>
            <p className="text-xs text-slate-500 mb-3">
              Spec plan ini dibaca engine provisioning saat invoice dibayar - VM dibuat persis sesuai angka di bawah
              (contoh plan: 1 vCPU, 1 GB RAM, 20 GB Storage). Opsi konfigurasi & add-on otomatis <b>menambah</b> resource
              di atas spec dasar ini. Template OS dipilih klien saat order dari template & cloud-init yang tersedia di
              server - kosongkan Template VMID kecuali ingin memaksa satu template tertentu.
            </p>
            <div className="grid grid-cols-4 gap-3">
              <label><div className={labelClass}>vCPU (core)</div><input type="number" min="0" value={f.provision?.cores || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, cores: e.target.value } })} className={inputClass} placeholder="1" data-testid="base-spec-cores" /></label>
              <label><div className={labelClass}>RAM (GB)</div><input type="number" min="0" step="0.5" value={f.provision?.ram_gb ?? ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, ram_gb: e.target.value } })} className={inputClass} placeholder="1" data-testid="base-spec-ram" /></label>
              <label><div className={labelClass}>Storage (GB)</div><input type="number" min="0" value={f.provision?.disk_gb || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, disk_gb: e.target.value } })} className={inputClass} placeholder="20" data-testid="base-spec-disk" /></label>
              <label><div className={labelClass}>Template VMID (ops.)</div><input type="number" min="0" value={f.provision?.template_vmid || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, template_vmid: e.target.value } })} className={inputClass} placeholder="auto" data-testid="base-spec-template" /></label>
            </div>
          </div>
        )}

        {/* ---------- Add-on attach settings ---------- */}
        {f.is_addon && (
          <div className="mt-5 border-t border-slate-200 pt-5">
            <div className="text-[11px] font-bold uppercase tracking-widest text-purple-800 mb-2">Add-on attaches to…</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className={labelClass}>Any product in categories</div>
                <div className="mt-1 grid grid-cols-2 gap-1 max-h-40 overflow-y-auto border border-slate-200 rounded-xl p-2">
                  {categories.map((c) => {
                    const on = (f.applies_to_categories || []).includes(c.slug);
                    return (
                      <label key={c.slug} className="flex items-center gap-1.5 text-sm px-1 py-0.5">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={(e) => {
                            const cur = new Set(f.applies_to_categories);
                            e.target.checked ? cur.add(c.slug) : cur.delete(c.slug);
                            setF({ ...f, applies_to_categories: [...cur] });
                          }}
                          data-testid={`addon-cat-${c.slug}`}
                        />
                        <span className="text-slate-700">{c.label}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
              <div>
                <div className={labelClass}>Or specific base products</div>
                <div className="mt-1 grid grid-cols-1 gap-1 max-h-40 overflow-y-auto border border-slate-200 rounded-xl p-2">
                  {allProducts.filter((x) => !x.is_addon && x.id !== p?.id).map((pp) => {
                    const on = (f.applies_to_product_ids || []).includes(pp.id);
                    return (
                      <label key={pp.id} className="flex items-center gap-1.5 text-sm px-1 py-0.5">
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={(e) => {
                            const cur = new Set(f.applies_to_product_ids);
                            e.target.checked ? cur.add(pp.id) : cur.delete(pp.id);
                            setF({ ...f, applies_to_product_ids: [...cur] });
                          }}
                        />
                        <span className="text-slate-700 truncate">{pp.name}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ---------- Add-on resource extras ---------- */}
        {f.is_addon && (
          <div className="mt-5 border-t border-slate-200 pt-5" data-testid="addon-resource-fields">
            <div className="text-[11px] font-bold uppercase tracking-widest text-purple-800 mb-1">Resource tambahan (auto-provisioning)</div>
            <p className="text-xs text-slate-500 mb-3">
              Bila add-on ini dibeli bersama produk VPS/Cloud, resource di bawah otomatis DITAMBAHKAN ke spesifikasi VM saat provisioning. Kosongkan (0) bila add-on tidak menambah resource.
            </p>
            <div className="grid grid-cols-4 gap-3">
              <label><div className={labelClass}>+ vCPU</div><input type="number" min="0" value={f.provision?.cores || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, cores: e.target.value } })} className={inputClass} placeholder="0" data-testid="addon-res-cores" /></label>
              <label><div className={labelClass}>+ RAM (MB)</div><input type="number" min="0" step="512" value={f.provision?.memory_mb || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, memory_mb: e.target.value } })} className={inputClass} placeholder="0" data-testid="addon-res-memory" /></label>
              <label><div className={labelClass}>+ Disk (GB)</div><input type="number" min="0" value={f.provision?.disk_gb || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, disk_gb: e.target.value } })} className={inputClass} placeholder="0" data-testid="addon-res-disk" /></label>
              <label><div className={labelClass}>+ IP publik</div><input type="number" min="0" value={f.provision?.ip || ""} onChange={(e) => setF({ ...f, provision: { ...f.provision, ip: e.target.value } })} className={inputClass} placeholder="0" data-testid="addon-res-ip" /></label>
            </div>
          </div>
        )}

        {/* ---------- Option groups (base products only) ---------- */}
        {!f.is_addon && (
          <div className="mt-5 border-t border-slate-200 pt-5">
            <div className="flex items-center justify-between mb-2">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350]">Configurable options</div>
                <div className="text-xs text-slate-500">e.g. RAM tiers, OS choice, IP quantity. Each option adds to the base price.</div>
              </div>
              <button
                type="button"
                onClick={() => setF({ ...f, option_groups: [...f.option_groups, emptyGroup()] })}
                className="text-xs font-bold text-[#0a2350] bg-slate-100 hover:bg-[#f5b120] hover:text-[#0a2350] px-3 py-1.5 rounded-lg"
                data-testid="add-option-group"
              >
                <Plus className="h-3 w-3 inline" /> Add option group
              </button>
            </div>

            {f.option_groups.map((g, gi) => (
              <OptionGroupEditor
                key={gi}
                g={g}
                onChange={(patch) => {
                  const next = [...f.option_groups];
                  next[gi] = { ...next[gi], ...patch };
                  setF({ ...f, option_groups: next });
                }}
                onRemove={() => setF({ ...f, option_groups: f.option_groups.filter((_, i) => i !== gi) })}
              />
            ))}
          </div>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>Cancel</button>
          <button type="submit" disabled={busy} className={btnPrimary} data-testid="p-submit">{p ? "Save changes" : "Create product"}</button>
        </div>
      </form>
    </div>
  );
};

const ProvisionSettings = ({ value, onChange }) => {
  const [templates, setTemplates] = useState([]);
  const [tplErr, setTplErr] = useState("");
  useEffect(() => {
    api.get("/admin/proxmox/templates")
      .then((r) => setTemplates(r.data.templates || []))
      .catch((e) => setTplErr(e?.response?.data?.detail || "Integrasi Proxmox belum aktif"));
  }, []);
  const set = (k, v) => onChange({ ...value, [k]: v });
  return (
    <div className="mt-5 border-t border-slate-200 pt-5" data-testid="product-provision-settings">
      <div className="text-[11px] font-bold uppercase tracking-widest text-[#0a2350] mb-1">Auto-provisioning (Proxmox)</div>
      <p className="text-xs text-slate-500 mb-3">
        Template & spesifikasi VM untuk paket ini. Saat klien memilih OS, sistem mencari template yang cocok dengan OS
        (auto-build bila belum ada) - template di bawah dipakai bila klien tidak memilih OS.
      </p>
      {tplErr && <div className="mb-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">{tplErr}</div>}
      <div className="grid grid-cols-2 gap-3">
        <label className="col-span-2"><div className={labelClass}>Template VM default (dari server Proxmox)</div>
          <select value={value.template_vmid || ""} onChange={(e) => set("template_vmid", e.target.value)} className={inputClass} data-testid="p-provision-template">
            <option value="">- Otomatis (match OS / template pertama) -</option>
            {templates.map((t) => <option key={t.vmid} value={t.vmid}>{t.name || "VM"} (VMID {t.vmid} · {t.node})</option>)}
          </select>
        </label>
        <label><div className={labelClass}>vCPU</div><input type="number" min="1" value={value.cores || ""} onChange={(e) => set("cores", e.target.value)} className={inputClass} placeholder="2" data-testid="p-provision-cores" /></label>
        <label><div className={labelClass}>RAM (MB)</div><input type="number" min="512" step="512" value={value.memory_mb || ""} onChange={(e) => set("memory_mb", e.target.value)} className={inputClass} placeholder="2048" data-testid="p-provision-memory" /></label>
        <label className="col-span-2"><div className={labelClass}>Disk (GB)</div><input type="number" min="10" value={value.disk_gb || ""} onChange={(e) => set("disk_gb", e.target.value)} className={inputClass} placeholder="40" data-testid="p-provision-disk" /></label>
      </div>
    </div>
  );
};

const OptionGroupEditor = ({ g, onChange, onRemove }) => {
  const [collapsed, setCollapsed] = useState(false);

  const setOption = (oi, patch) => {
    const opts = [...(g.options || [])];
    opts[oi] = { ...opts[oi], ...patch };
    onChange({ options: opts });
  };
  const addOption = () => onChange({ options: [...(g.options || []), emptyOption()] });
  const rmOption = (oi) => onChange({ options: g.options.filter((_, i) => i !== oi) });

  return (
    <div className="border border-slate-200 rounded-2xl p-4 mt-3 bg-slate-50/60" data-testid={`option-group-${g.key || "new"}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 flex-1">
          <input placeholder="key (e.g., ram)" value={g.key} onChange={(e) => onChange({ key: e.target.value })} className={`${inputClass} max-w-[140px] font-mono text-xs`} />
          <input placeholder="Label (e.g., RAM)" value={g.label} onChange={(e) => onChange({ label: e.target.value })} className={`${inputClass} max-w-[200px]`} />
          <select value={g.type} onChange={(e) => onChange({ type: e.target.value })} className={`${inputClass} max-w-[140px]`}>
            <option value="dropdown">Dropdown</option>
            <option value="checkbox">Checkbox</option>
            <option value="quantity">Quantity</option>
          </select>
          <label className="text-xs flex items-center gap-1">
            <input type="checkbox" checked={g.required} onChange={(e) => onChange({ required: e.target.checked })} /> required
          </label>
        </div>
        <button type="button" onClick={() => setCollapsed(!collapsed)} className="text-slate-500 hover:text-[#0a2350]">
          {collapsed ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </button>
        <button type="button" onClick={onRemove} className="text-slate-500 hover:text-red-600 ml-2"><X className="h-4 w-4" /></button>
      </div>

      {!collapsed && (
        <div className="mt-3">
          {g.type === "quantity" ? (
            <div className="grid grid-cols-3 gap-2">
              <label><div className={labelClass}>Unit label</div><input placeholder="IP, GB, core" value={g.unit_label} onChange={(e) => onChange({ unit_label: e.target.value })} className={inputClass} /></label>
              <label><div className={labelClass}>Unit / month</div><input type="number" value={g.unit_price_monthly} onChange={(e) => onChange({ unit_price_monthly: Number(e.target.value) })} className={inputClass} /></label>
              <label><div className={labelClass}>Unit setup</div><input type="number" value={g.unit_price_setup} onChange={(e) => onChange({ unit_price_setup: Number(e.target.value) })} className={inputClass} /></label>
              <label><div className={labelClass}>Min</div><input type="number" value={g.min_qty} onChange={(e) => onChange({ min_qty: Number(e.target.value) })} className={inputClass} /></label>
              <label><div className={labelClass}>Max</div><input type="number" value={g.max_qty} onChange={(e) => onChange({ max_qty: Number(e.target.value) })} className={inputClass} /></label>
              <label><div className={labelClass}>Step</div><input type="number" value={g.step_qty} onChange={(e) => onChange({ step_qty: Number(e.target.value) })} className={inputClass} /></label>
            </div>
          ) : (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-500 grid grid-cols-[1fr_100px_100px_80px_20px] gap-2 mb-1 px-1">
                <div>Option label</div><div>+ Monthly</div><div>+ Setup</div><div>Default</div><div></div>
              </div>
              {(g.options || []).map((o, oi) => (
                <div key={oi} className="grid grid-cols-[1fr_100px_100px_80px_20px] gap-2 mb-1.5 items-center">
                  <input placeholder="e.g. 4 GB" value={o.label} onChange={(e) => setOption(oi, { label: e.target.value })} className={`${inputClass} h-9`} />
                  <input type="number" value={o.price_monthly_delta} onChange={(e) => setOption(oi, { price_monthly_delta: Number(e.target.value) })} className={`${inputClass} h-9`} />
                  <input type="number" value={o.price_setup_delta} onChange={(e) => setOption(oi, { price_setup_delta: Number(e.target.value) })} className={`${inputClass} h-9`} />
                  <label className="flex items-center gap-1 text-xs justify-center">
                    <input type="checkbox" checked={o.is_default} onChange={(e) => setOption(oi, { is_default: e.target.checked })} />
                  </label>
                  <button type="button" onClick={() => rmOption(oi)} className="text-slate-500 hover:text-red-600"><X className="h-3.5 w-3.5" /></button>
                </div>
              ))}
              <button type="button" onClick={addOption} className="text-xs text-[#0a2350] font-bold hover:text-[#f5b120] mt-1">+ add option</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default AdminProducts;
