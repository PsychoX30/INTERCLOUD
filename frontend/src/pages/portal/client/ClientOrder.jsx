import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, money, shortDate, fullDateTime } from "../../../portal/api";
import { PageHeader, Card, Loading, EmptyState, StatusBadge, btnPrimary, btnSecondary, inputClass, labelClass } from "../ui";
import {
  CheckCircle2, ShoppingCart, Cpu, ArrowRight, ArrowLeft, Circle, PackagePlus,
  ClipboardCheck, Send, Loader2, X, Package, Puzzle, ReceiptText,
} from "lucide-react";

/* -------------------------------------------------------------------------
   WHMCS-style order flow — 5 steps:
     1. Pick a product          (browse categories)
     2. Configure options       (RAM / CPU / OS / quantities)
     3. Attach add-ons          (optional)
     4. Review the cart         (price breakdown, confirm)
     5. Order placed            (redirect target: /invoices/{id})
   ------------------------------------------------------------------------- */

const STEPS = [
  { key: "pick",      label: "Pick a plan",   icon: Package },
  { key: "configure", label: "Configure",     icon: Cpu },
  { key: "addons",    label: "Add-ons",       icon: Puzzle },
  { key: "review",    label: "Review & pay",  icon: ClipboardCheck },
];

const idr = (v) => "Rp" + Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });

/* ============ Step 1 — pick a product from categories ============ */
const StepPick = ({ products, categories, chosen, setChosen, onNext }) => {
  const [cat, setCat] = useState(categories[0]?.slug || "");
  const list = useMemo(
    () => products.filter((p) => (!cat || p.category === cat) && p.is_active && !p.is_addon),
    [products, cat]
  );
  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2 mb-4" data-testid="order-category-tabs">
        {categories.map((c) => (
          <button
            key={c.slug}
            onClick={() => setCat(c.slug)}
            data-testid={`order-cat-${c.slug}`}
            className={`h-9 px-4 rounded-full text-xs font-bold uppercase tracking-widest transition-colors ${
              cat === c.slug ? "bg-[#0a2350] text-white" : "bg-white text-slate-500 border border-slate-200 hover:border-[#0a2350] hover:text-[#0a2350]"
            }`}
          >
            {c.label} <span className="opacity-60">({c.product_count})</span>
          </button>
        ))}
      </div>

      {list.length === 0 && <EmptyState title="No products in this category yet" />}
      <div className="grid md:grid-cols-2 gap-3">
        {list.map((p) => {
          const selected = chosen?.id === p.id;
          return (
            <button
              key={p.id}
              onClick={() => setChosen(p)}
              data-testid={`order-product-${p.id}`}
              className={`text-left p-5 rounded-2xl border-2 transition-all ${
                selected
                  ? "border-[#f5b120] bg-orange-50/50 ring-4 ring-[#f5b120]/10"
                  : "border-slate-200 bg-white hover:border-[#0a2350]"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1">
                  <div className="font-extrabold text-[#0a2350] text-lg">{p.name}</div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-[#f5b120] mt-0.5">{p.category}</div>
                  <div className="text-sm text-slate-500 mt-2">{p.description}</div>
                </div>
                {selected && <CheckCircle2 className="h-5 w-5 text-[#f5b120] flex-shrink-0" />}
              </div>

              <ul className="mt-3 space-y-1 text-xs text-slate-600">
                {(p.features || []).slice(0, 4).map((f, i) => (
                  <li key={i} className="flex items-center gap-1.5">
                    <Circle className="h-1.5 w-1.5 fill-[#f5b120] text-[#f5b120]" strokeWidth={0} />
                    {f}
                  </li>
                ))}
              </ul>

              <div className="mt-3 pt-3 border-t border-slate-200 flex justify-between items-end">
                <div>
                  <div className="text-2xl font-extrabold text-[#0a2350]">
                    {p.price_monthly ? idr(p.price_monthly) : "Custom"}
                  </div>
                  {p.price_monthly > 0 && <div className="text-[10px] text-slate-500">/ month</div>}
                </div>
                {p.setup_fee > 0 && (
                  <div className="text-right">
                    <div className="text-[10px] uppercase text-slate-400 tracking-wider font-bold">Setup</div>
                    <div className="text-sm font-bold text-slate-600">{idr(p.setup_fee)}</div>
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-6 flex justify-end">
        <button
          disabled={!chosen}
          onClick={onNext}
          data-testid="order-step-continue"
          className={`${btnPrimary} ${!chosen ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          Continue <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
};

/* ============ Step 2 — configure options for the chosen product ============ */
const StepConfigure = ({ product, selections, setSelections, onNext, onBack }) => {
  const groups = product.option_groups || [];

  // Ensure every required dropdown has a default value
  useEffect(() => {
    const initial = {};
    for (const g of groups) {
      if (g.type === "dropdown") {
        const defaultOpt = (g.options || []).find((o) => o.is_default) || (g.options || [])[0];
        initial[g.key] = { group_key: g.key, option_labels: defaultOpt ? [defaultOpt.label] : [] };
      } else if (g.type === "checkbox") {
        initial[g.key] = { group_key: g.key, option_labels: [] };
      } else if (g.type === "quantity") {
        initial[g.key] = { group_key: g.key, quantity: g.min_qty || 0 };
      }
    }
    // Merge on top of existing selections so user's picks survive Back/Next
    setSelections((prev) => {
      const map = {};
      for (const s of prev) map[s.group_key] = s;
      const merged = { ...initial, ...map };
      return Object.values(merged);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.id]);

  const setForGroup = (key, patch) => {
    setSelections((prev) => {
      const idx = prev.findIndex((s) => s.group_key === key);
      const next = [...prev];
      if (idx >= 0) next[idx] = { ...next[idx], ...patch };
      else next.push({ group_key: key, ...patch });
      return next;
    });
  };
  const getForGroup = (key) => selections.find((s) => s.group_key === key) || {};

  if (groups.length === 0) {
    return (
      <div className="mt-6">
        <Card className="p-6 text-slate-600">
          <div className="font-bold text-[#0a2350] mb-1">No configuration needed</div>
          This product ships with fixed specs. Click Continue to review your order.
        </Card>
        <div className="mt-6 flex justify-between">
          <button onClick={onBack} className={btnSecondary}><ArrowLeft className="h-4 w-4" /> Back</button>
          <button onClick={onNext} className={btnPrimary} data-testid="order-step-continue">Continue <ArrowRight className="h-4 w-4" /></button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-4">
      {groups.map((g) => (
        <Card key={g.key} className="p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold text-slate-400">
                {g.type} {g.required ? "· required" : "· optional"}
              </div>
              <div className="font-extrabold text-[#0a2350] text-lg">{g.label}</div>
            </div>
          </div>

          {g.type === "dropdown" && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {(g.options || []).map((opt) => {
                const active = (getForGroup(g.key).option_labels || []).includes(opt.label);
                const delta = (opt.price_monthly_delta || 0);
                const setupDelta = (opt.price_setup_delta || 0);
                return (
                  <button
                    key={opt.label}
                    onClick={() => setForGroup(g.key, { option_labels: [opt.label] })}
                    data-testid={`order-opt-${g.key}-${opt.label.replace(/\s+/g,'-')}`}
                    className={`text-left p-3 rounded-xl border-2 transition-colors ${
                      active
                        ? "border-[#f5b120] bg-orange-50/60"
                        : "border-slate-200 bg-white hover:border-[#0a2350]"
                    }`}
                  >
                    <div className="font-bold text-[#0a2350] text-sm">{opt.label}</div>
                    <div className="text-[11px] mt-0.5">
                      {delta > 0 ? <span className="text-slate-600">+{idr(delta)}/mo</span> : <span className="text-emerald-600 font-semibold">included</span>}
                      {setupDelta > 0 && <span className="text-slate-500"> · +{idr(setupDelta)} setup</span>}
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          {g.type === "checkbox" && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {(g.options || []).map((opt) => {
                const active = (getForGroup(g.key).option_labels || []).includes(opt.label);
                return (
                  <label
                    key={opt.label}
                    className={`flex items-center gap-3 p-3 rounded-xl border-2 cursor-pointer ${
                      active ? "border-[#f5b120] bg-orange-50/60" : "border-slate-200 bg-white hover:border-[#0a2350]"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={(e) => {
                        const cur = new Set(getForGroup(g.key).option_labels || []);
                        e.target.checked ? cur.add(opt.label) : cur.delete(opt.label);
                        setForGroup(g.key, { option_labels: [...cur] });
                      }}
                      data-testid={`order-check-${g.key}-${opt.label.replace(/\s+/g,'-')}`}
                    />
                    <div className="flex-1">
                      <div className="font-bold text-[#0a2350] text-sm">{opt.label}</div>
                      <div className="text-[11px] text-slate-500">
                        {opt.price_monthly_delta > 0 ? `+${idr(opt.price_monthly_delta)}/mo` : "free"}
                        {opt.price_setup_delta > 0 ? ` · +${idr(opt.price_setup_delta)} setup` : ""}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}

          {g.type === "quantity" && (
            <div className="flex items-center gap-4">
              <input
                type="number"
                min={g.min_qty || 0}
                max={g.max_qty || 100}
                step={g.step_qty || 1}
                value={getForGroup(g.key).quantity ?? (g.min_qty || 0)}
                onChange={(e) => setForGroup(g.key, { quantity: Number(e.target.value) })}
                className={`${inputClass} max-w-[120px]`}
                data-testid={`order-qty-${g.key}`}
              />
              <div className="text-sm text-slate-500">
                <b>{g.unit_label || "unit"}</b> — {idr(g.unit_price_monthly || 0)}/mo each
                {(g.unit_price_setup || 0) > 0 && ` · +${idr(g.unit_price_setup)} setup each`}
              </div>
            </div>
          )}
        </Card>
      ))}

      <div className="mt-6 flex justify-between">
        <button onClick={onBack} className={btnSecondary}><ArrowLeft className="h-4 w-4" /> Back</button>
        <button onClick={onNext} className={btnPrimary} data-testid="order-step-continue">Continue <ArrowRight className="h-4 w-4" /></button>
      </div>
    </div>
  );
};

/* ============ Step 3 — pick optional add-ons ============ */
const StepAddons = ({ product, allAddons, addonIds, setAddonIds, onNext, onBack }) => {
  const applicable = useMemo(
    () => allAddons.filter((a) =>
      (a.applies_to_categories || []).includes(product.category) ||
      (a.applies_to_product_ids || []).includes(product.id)
    ),
    [allAddons, product]
  );

  const toggle = (id) => {
    setAddonIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  return (
    <div className="mt-4">
      {applicable.length === 0 ? (
        <Card className="p-6 text-slate-600">
          <div className="font-bold text-[#0a2350] mb-1">No add-ons available</div>
          Nothing extra to attach to this product. You can proceed to the review step.
        </Card>
      ) : (
        <div className="grid md:grid-cols-2 gap-3">
          {applicable.map((a) => {
            const active = addonIds.includes(a.id);
            return (
              <button
                key={a.id}
                onClick={() => toggle(a.id)}
                data-testid={`order-addon-${a.id}`}
                className={`text-left p-5 rounded-2xl border-2 transition-all ${
                  active
                    ? "border-[#f5b120] bg-orange-50/50 ring-4 ring-[#f5b120]/10"
                    : "border-slate-200 bg-white hover:border-[#0a2350]"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <div className="font-extrabold text-[#0a2350] text-lg flex items-center gap-2">
                      <Puzzle className="h-4 w-4 text-[#f5b120]" /> {a.name}
                    </div>
                    <div className="text-sm text-slate-500 mt-1">{a.description}</div>
                  </div>
                  {active && <CheckCircle2 className="h-5 w-5 text-[#f5b120] flex-shrink-0" />}
                </div>
                <div className="mt-3 pt-3 border-t border-slate-200 flex justify-between items-center">
                  <div className="font-extrabold text-[#0a2350]">
                    {idr(a.price_monthly)}<span className="text-xs text-slate-500 font-normal">/mo</span>
                  </div>
                  {a.setup_fee > 0 && (
                    <div className="text-xs text-slate-500">+{idr(a.setup_fee)} setup</div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-6 flex justify-between">
        <button onClick={onBack} className={btnSecondary}><ArrowLeft className="h-4 w-4" /> Back</button>
        <button onClick={onNext} className={btnPrimary} data-testid="order-step-continue">Review order <ArrowRight className="h-4 w-4" /></button>
      </div>
    </div>
  );
};

/* ============ Step 4 — review cart, confirm, generate invoice ============ */
const StepReview = ({ product, selections, addonIds, notes, setNotes, onBack, onConfirmed }) => {
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .post("/orders/preview", { product_id: product.id, selections, addon_ids: addonIds })
      .then((r) => setPreview(r.data))
      .catch((e) => setErr(e?.response?.data?.detail || "Failed to price cart"));
  }, [product.id, selections, addonIds]);

  const confirm = async () => {
    setBusy(true); setErr("");
    try {
      const { data } = await api.post("/client/orders", {
        product_id: product.id, selections, addon_ids: addonIds, notes,
      });
      onConfirmed(data);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Failed to place order");
    } finally {
      setBusy(false);
    }
  };

  if (err && !preview) {
    return (
      <div className="mt-4">
        <Card className="p-6 text-red-700 bg-red-50 border-red-200">{err}</Card>
        <div className="mt-6"><button onClick={onBack} className={btnSecondary}><ArrowLeft className="h-4 w-4" /> Back</button></div>
      </div>
    );
  }
  if (!preview) return <Loading />;

  const Row = ({ label, value, muted, bold, top }) => (
    <div className={`flex justify-between text-sm ${top ? "border-t border-slate-200 pt-3 mt-3" : ""}`}>
      <span className={muted ? "text-slate-500" : bold ? "font-extrabold text-[#0a2350] text-base" : "text-slate-700"}>{label}</span>
      <span className={bold ? "font-extrabold text-[#0a2350] text-base" : "font-semibold text-slate-800"}>{value}</span>
    </div>
  );

  return (
    <div className="mt-4 grid md:grid-cols-3 gap-4">
      <Card className="p-6 md:col-span-2" data-testid="order-review-details">
        <div className="text-[10px] uppercase tracking-widest font-bold text-slate-400">Order summary</div>
        <div className="text-xl font-extrabold text-[#0a2350] mt-1">{product.name}</div>
        <div className="text-xs text-slate-500 uppercase tracking-widest font-bold">{product.category}</div>

        <div className="mt-5 space-y-2.5">
          <Row label={`${product.name} — base plan (monthly)`} value={idr(preview.base_line.monthly)} />
          {preview.base_line.setup > 0 && <Row label={`${product.name} — setup fee`} value={idr(preview.base_line.setup)} muted />}

          {preview.option_lines.length > 0 && <div className="text-[10px] uppercase tracking-widest font-bold text-slate-400 mt-4">Configuration</div>}
          {preview.option_lines.map((ol, i) => (
            <React.Fragment key={i}>
              {ol.monthly > 0 && <Row label={`${ol.group_label}: ${ol.choice}`} value={`+${idr(ol.monthly)}/mo`} muted />}
              {ol.setup > 0 && <Row label={`${ol.group_label}: ${ol.choice} — setup`} value={`+${idr(ol.setup)}`} muted />}
            </React.Fragment>
          ))}

          {preview.addon_lines.length > 0 && <div className="text-[10px] uppercase tracking-widest font-bold text-slate-400 mt-4">Add-ons</div>}
          {preview.addon_lines.map((al, i) => (
            <React.Fragment key={i}>
              <Row label={`Add-on: ${al.name}`} value={`+${idr(al.monthly)}/mo`} muted />
              {al.setup > 0 && <Row label={`Add-on: ${al.name} — setup`} value={`+${idr(al.setup)}`} muted />}
            </React.Fragment>
          ))}
        </div>

        <label className="mt-6 block">
          <div className={labelClass}>Notes for our team (optional)</div>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            data-testid="order-notes"
            className={`${inputClass} mt-1`}
            placeholder="e.g., preferred deployment window, technical contact, region preference…"
          />
        </label>
      </Card>

      <Card className="p-6 h-fit sticky top-20" data-testid="order-review-total">
        <div className="text-[10px] uppercase tracking-widest font-bold text-slate-400">Total due today</div>
        <div className="text-3xl font-extrabold text-[#0a2350] mt-1" data-testid="order-total">{idr(preview.total)}</div>
        <div className="text-xs text-slate-500 mt-0.5">Recurring: <b>{idr(preview.subtotal_monthly)}</b>/mo</div>

        <div className="mt-5 space-y-1.5">
          <Row label="Recurring subtotal" value={idr(preview.subtotal_monthly)} muted />
          <Row label="Setup fees" value={idr(preview.setup_total)} muted />
          <Row label={`Tax (${preview.tax_percent}%)`} value={idr(preview.tax_amount)} muted />
          <Row label="Total" value={idr(preview.total)} bold top />
        </div>

        {err && <div className="mt-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{err}</div>}

        <button
          onClick={confirm}
          disabled={busy}
          data-testid="order-confirm-btn"
          className={`${btnPrimary} w-full mt-5`}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ReceiptText className="h-4 w-4" />}
          {busy ? "Placing order…" : "Confirm & Generate Invoice"}
        </button>
        <button onClick={onBack} className={`${btnSecondary} w-full mt-2`} disabled={busy}>
          <ArrowLeft className="h-4 w-4" /> Back to edit
        </button>
        <p className="mt-3 text-[11px] text-slate-500">
          By confirming, you agree an invoice will be issued for {idr(preview.total)}. Service is auto-provisioned once payment is verified.
        </p>
      </Card>
    </div>
  );
};

/* ============ Step 5 — success ============ */
const StepDone = ({ result, onNewOrder }) => (
  <div className="mt-4">
    <Card className="p-8 text-center" data-testid="order-done">
      <div className="h-16 w-16 mx-auto rounded-full bg-emerald-100 flex items-center justify-center">
        <CheckCircle2 className="h-9 w-9 text-emerald-600" />
      </div>
      <h3 className="text-2xl font-extrabold text-[#0a2350] mt-4">Order placed successfully</h3>
      <p className="mt-2 text-slate-600 max-w-md mx-auto">
        {result.invoice_id
          ? "An invoice has been generated. Pay via bank transfer or the payment gateway — we auto-provision the moment payment is verified."
          : "This is a custom-priced product. Our sales team will send you a formal quotation shortly."}
      </p>
      <div className="mt-6 inline-flex gap-2 flex-wrap justify-center">
        {result.invoice_id ? (
          <Link to="/portal/client/invoices" className={btnPrimary} data-testid="go-to-invoice">
            View invoice <ArrowRight className="h-4 w-4" />
          </Link>
        ) : (
          <Link to="/portal/client/tickets" className={btnPrimary}>Open a ticket</Link>
        )}
        <button onClick={onNewOrder} className={btnSecondary}><PackagePlus className="h-4 w-4" /> Order another</button>
      </div>
    </Card>
  </div>
);

/* ============ Orchestrator ============ */
const ClientOrder = () => {
  const [products, setProducts] = useState(null);
  const [addons, setAddons] = useState([]);
  const [categories, setCategories] = useState([]);
  const [step, setStep] = useState(0); // 0..3 = flow, 4 = done
  const [chosen, setChosen] = useState(null);
  const [selections, setSelections] = useState([]);
  const [addonIds, setAddonIds] = useState([]);
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState(null);
  const [orders, setOrders] = useState([]);

  const loadOrders = () => api.get("/client/orders").then((r) => setOrders(r.data));

  useEffect(() => {
    Promise.all([
      api.get("/portal-public/products"),
      api.get("/portal-public/addons"),
      api.get("/portal-public/categories"),
    ]).then(([p, a, c]) => {
      setProducts(p.data);
      setAddons(a.data);
      // Only categories that have at least 1 active product available for order
      const withCounts = c.data.map((cat) => ({
        ...cat,
        product_count: p.data.filter((pr) => pr.category === cat.slug && !pr.is_addon && pr.is_active).length,
      })).filter((cat) => cat.product_count > 0);
      setCategories(withCounts);
    });
    loadOrders();
  }, []);

  if (!products) return <Loading />;

  const stepper = (
    <div className="flex items-center gap-2 mt-4" data-testid="order-stepper">
      {STEPS.map((s, i) => {
        const Icon = s.icon;
        const state = i < step ? "done" : i === step ? "current" : "todo";
        return (
          <React.Fragment key={s.key}>
            <div className={`flex items-center gap-2 ${state === "todo" ? "text-slate-400" : "text-[#0a2350]"}`}>
              <div className={`h-8 w-8 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-extrabold ${
                state === "done" ? "bg-emerald-500 text-white"
                : state === "current" ? "bg-[#f5b120] text-[#0a2350]"
                : "bg-slate-200 text-slate-500"
              }`}>
                {state === "done" ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
              </div>
              <span className="text-xs font-bold uppercase tracking-widest hidden md:inline">{s.label}</span>
            </div>
            {i < STEPS.length - 1 && <div className={`flex-1 h-0.5 ${i < step ? "bg-emerald-500" : "bg-slate-200"}`} />}
          </React.Fragment>
        );
      })}
    </div>
  );

  const restart = () => {
    setStep(0);
    setChosen(null);
    setSelections([]);
    setAddonIds([]);
    setNotes("");
    setResult(null);
  };

  return (
    <div>
      <PageHeader
        title="Order a new service"
        subtitle="Pick a plan → configure → attach add-ons → review your total → confirm. Invoice is generated the moment you confirm."
      />

      {step < STEPS.length && stepper}

      {step === 0 && (
        <StepPick
          products={products}
          categories={categories}
          chosen={chosen}
          setChosen={setChosen}
          onNext={() => setStep(1)}
        />
      )}

      {step === 1 && chosen && (
        <StepConfigure
          product={chosen}
          selections={selections}
          setSelections={setSelections}
          onBack={() => setStep(0)}
          onNext={() => setStep(2)}
        />
      )}

      {step === 2 && chosen && (
        <StepAddons
          product={chosen}
          allAddons={addons}
          addonIds={addonIds}
          setAddonIds={setAddonIds}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
        />
      )}

      {step === 3 && chosen && (
        <StepReview
          product={chosen}
          selections={selections}
          addonIds={addonIds}
          notes={notes}
          setNotes={setNotes}
          onBack={() => setStep(2)}
          onConfirmed={(r) => { setResult(r); setStep(4); loadOrders(); }}
        />
      )}

      {step === 4 && result && (
        <StepDone result={result} onNewOrder={restart} />
      )}

      {/* Order history */}
      {step < STEPS.length && orders.length > 0 && (
        <div className="mt-10">
          <div className="text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">Order history</div>
          <div className="rounded-2xl bg-white border border-slate-200 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="bg-slate-50 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">Product</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Placed</th>
                  <th className="px-4 py-3 text-right">Invoice</th>
                </tr>
              </thead>
              <tbody>
                {orders.slice(0, 10).map((o) => (
                  <tr key={o.id} className="border-t border-slate-100">
                    <td className="px-4 py-3 font-semibold text-[#0a2350]">{o.product_name}</td>
                    <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
                    <td className="px-4 py-3 text-slate-500">{shortDate(o.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      {o.invoice_id ? (
                        <Link to="/portal/client/invoices" className="text-[#f5b120] font-semibold text-xs">View →</Link>
                      ) : (
                        <span className="text-slate-400 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

export default ClientOrder;
