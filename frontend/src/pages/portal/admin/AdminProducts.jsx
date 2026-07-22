import React, { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api, money } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import { Edit, Trash2, Plus, ChevronDown, ChevronUp, X, Puzzle, Package } from "lucide-react";

/* ---------------------------------------------------------------
   Admin Products page — WHMCS-style catalog editor
   • Categories load from /admin/categories (dynamic)
   • Option groups: dropdown / checkbox / quantity, with per-option
     monthly/setup deltas and defaults
   • Add-ons: is_addon flag + applies_to_categories / product_ids
   --------------------------------------------------------------- */

const AdminProducts = () => {
  const location = useLocation();
  const initialFilter = location.pathname.endsWith("/addons") ? "addons" : "all";
  const [rows, setRows] = useState(null);
  const [cats, setCats] = useState([]);
  const [editing, setEditing] = useState(null);
  const [filter, setFilter] = useState(initialFilter); // all | base | addons

  useEffect(() => {
    setFilter(location.pathname.endsWith("/addons") ? "addons" : "all");
  }, [location.pathname]);

  const load = () => Promise.all([
    api.get("/admin/products"),
    api.get("/admin/categories"),
  ]).then(([p, c]) => { setRows(p.data); setCats(c.data); });

  useEffect(() => { load(); }, []);
  if (!rows) return <Loading />;

  const visible = rows.filter((p) =>
    filter === "all" ? true : filter === "addons" ? p.is_addon : !p.is_addon
  );

  return (
    <div>
      <PageHeader
        title="Products & Services"
        subtitle="Base plans, add-ons, and per-plan configurable options — visible to clients during the order flow."
        actions={<button className={btnPrimary} onClick={() => setEditing("new")} data-testid="new-product-btn"><Plus className="h-4 w-4" /> New product</button>}
      />

      <div className="flex gap-2 mb-3">
        {["all", "base", "addons"].map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            data-testid={`filter-${f}`}
            className={`h-8 px-3 rounded-full text-xs font-bold uppercase tracking-widest ${
              filter === f ? "bg-[#0a2350] text-white" : "bg-white text-slate-500 border border-slate-200"
            }`}
          >
            {f === "all" ? `All (${rows.length})` : f === "base" ? `Base plans (${rows.filter((r) => !r.is_addon).length})` : `Add-ons (${rows.filter((r) => r.is_addon).length})`}
          </button>
        ))}
      </div>

      {visible.length === 0 && <EmptyState title="No products in this view" />}
      {visible.length > 0 && (
        <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-widest text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Category</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Options</th>
                <th className="px-4 py-3 text-right">Monthly</th>
                <th className="px-4 py-3 text-right">Setup</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((p) => (
                <tr key={p.id} className="border-t border-slate-100" data-testid={`product-${p.id}`}>
                  <td className="px-4 py-3">
                    <div className="font-semibold text-[#0a2350]">{p.name}</div>
                    <div className="text-xs text-slate-500 line-clamp-1">{p.description}</div>
                  </td>
                  <td className="px-4 py-3 uppercase text-xs font-bold text-[#f5b120]">{p.category}</td>
                  <td className="px-4 py-3">
                    {p.is_addon ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase bg-purple-100 text-purple-700 px-2 py-0.5 rounded"><Puzzle className="h-3 w-3" /> Add-on</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase bg-slate-100 text-slate-700 px-2 py-0.5 rounded"><Package className="h-3 w-3" /> Base</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {(p.option_groups || []).length > 0 ? `${p.option_groups.length} groups` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-semibold">{p.price_monthly ? money(p.price_monthly) : "—"}</td>
                  <td className="px-4 py-3 text-right">{p.setup_fee ? money(p.setup_fee) : "—"}</td>
                  <td className="px-4 py-3"><StatusBadge status={p.is_active ? "enabled" : "disabled"} /></td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => setEditing(p)} className="text-slate-600 hover:text-[#f5b120]"><Edit className="h-4 w-4 inline" /></button>
                    <button
                      onClick={async () => {
                        if (window.confirm(`Delete "${p.name}"?`)) { await api.delete(`/admin/products/${p.id}`); load(); }
                      }}
                      className="text-slate-600 hover:text-red-600 ml-3"
                    ><Trash2 className="h-4 w-4 inline" /></button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
              <option value="y">Enabled — visible to clients</option>
              <option value="n">Disabled — hidden</option>
            </select>
          </label>

          <label className="col-span-2"><div className={labelClass}>Description</div><textarea rows={2} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} className={`${inputClass} h-auto py-2`} /></label>
          <label className="col-span-2"><div className={labelClass}>Features (one per line)</div><textarea rows={4} value={f.features} onChange={(e) => setF({ ...f, features: e.target.value })} className={`${inputClass} h-auto py-2 font-mono text-xs`} /></label>
        </div>

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
