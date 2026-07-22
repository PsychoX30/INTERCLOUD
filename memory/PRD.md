# Intercloud Digital Inovasi - Landing Page

## Original Problem Statement
Build a landing page for **PT. Intercloud Digital Inovasi** (Indonesia) based on `intercloud-digital.com` and user-provided reference carousels. Highlight 8 offerings: Cloud, Hosting, VPS, Colocation, Dedicated Server, Lease to Own Appliance, Firewall Solution, DC to DC Connectivity. Include interactive service cards with detail modals + WhatsApp CTAs, SEO (title, meta, OG, JSON-LD), and expandable FAQ.

## Product Choices
- Language: Indonesian primary
- Contact: WhatsApp `+62 878-1239-7187` (`6287812397187`), email `support@intercloud-digital.com`
- Brand: Navy (`#0a2350`) + amber (`#f5b120`); real logo from `intercloud-digital.com`
- Backend: none — WhatsApp-only for now
- Content depth: Each service modal has Overview → Signals ("Kapan bisnis butuh") → Use-Cases ("Cocok untuk") → Comparison ("Dibanding alternatif") → Features & Specs, matching the user's marketing carousel pattern

## Architecture
- Frontend: React (CRA) + Tailwind + Radix/shadcn Dialog & Accordion + lucide-react icons + Plus Jakarta Sans
- Backend/DB: **not used** (fully static; MOCKED contact via WhatsApp deep links)

## Implemented (2026-02)
- Header with real logo, sticky, transparent-to-navy on scroll, mobile drawer
- Hero: navy background, yellow curved accent + wave, data-center image, stat pill (SLA 99.5% / 24/7 / Tier III)
- Features (Why Us): 4 cards (Harga Kompetitif, Support 24/7, Koneksi Stabil, SLA 99,5%)
- Services: 9 cards with hover lift, tags, "Mulai dari" price. Click opens rich modal:
  - Overview, Signals, Use-Cases grid, Comparison callout, Features grid, sticky WA CTA (pre-filled msg)
- **Decision Guide** (NEW): 3-card panduan pemilihan (Hosting/VPS/Dedicated) with numbered steps + "Belum yakin pilih yang mana?" WA bar — mirrors user's reference carousel
- Pricing: **3-tab detailed catalog** (Katalog Layanan)
  - Dedicated Server: 8/16/24/32 Core (16 Core featured)
  - Colocation: 1U, 2U, 4U, 5U (featured), 10U, 20U, 40U, 1U Router/Switch APJII
  - Interconnect & BGP: DC Interconnect, Local Remote-IX, BGP Domestik (featured), BGP Content Mix, BGP SGIX
  - Custom-quote CTA strip at the bottom
- Partners: 16-logo marquee with edge fade
- FAQ: 9 Q&A shadcn accordion with sidebar contact card
- CTA: navy CTA section with 3 contact cards
- Footer: real logo, address, socials, page & service link lists
- Floating WhatsApp button with pulse animation
- SEO: title, meta description, keywords, OpenGraph, Twitter cards, Organization + FAQPage JSON-LD, Plus Jakarta Sans preload

## Files of Reference
- `/app/frontend/src/pages/Landing.jsx`
- `/app/frontend/src/components/{Header,Hero,Features,Services,DecisionGuide,Pricing,Partners,FAQ,CTA,Footer}.jsx`
- `/app/frontend/src/mock/data.js` — all service copy + WhatsApp/email constants
- `/app/frontend/src/App.css` — brand palette, animations, marquee, wa-pulse
- `/app/frontend/public/index.html` — SEO + structured data

## Implemented (2026-02, latest batch)
- **Infrastructure "How We Power Your Business" section** — 4 photo-illustrated cards (Data Center Facility, Servers & Compute, Fiber Connectivity, Global Network) + a 4-step traffic-journey strip (01→04). Live Unsplash imagery, EN/ID translated
- **Icon overhaul** for better semantic fit:
  - Features: `Wifi` → `Network` (connectivity), `ShieldCheck` (SLA) → `Gauge`
  - Services: Hosting `Globe2` → `LayoutTemplate`; VPS `Boxes` → `Container`; Colocation `Server` → `Warehouse`; Dedicated `HardDrive` → `Server`; Lease-to-Own `Building2` → `HandCoins`; DC-to-DC `Cable` → `Waypoints`
  - PoP APJII: `Radio` → `Waypoints`
- **Verified**: `testing_agent_v3_fork` iteration_3 — 100% pass; all 4 Unsplash images load (naturalWidth=1000), all SVG icons render, EN/ID toggle works, no regressions on modals/tabs/FAQ

## Implemented (2026-02, prior batch)
- **Bilingual EN/ID toggle** (React Context `LanguageContext`, persists via `localStorage.ic_lang`, default `id`, updates `<html lang>`) — desktop + mobile LanguageToggle pills
- Every section (Header, Hero, Features, Services + modals, DecisionGuide, Pricing tabs + plans, Partners, PoP, FAQ, CTA, Footer) reads localized `{id,en}` strings via `useLang()`/`pick()`
- Firewall pricing changed to "Contact us for pricing" / "Hubungi kami untuk harga"
- **Points of Presence (PoP)** section with 4 DCs: Metta DC Cyber 1 5th floor, Omni DC Cyber 1 2nd floor, TIFA Building, APJII DC Cyber 1 1st floor
- WhatsApp CTA number standardized to `6287812397187` across 15 links
- **Verified**: `testing_agent_v3_fork` iteration_2 — 100% pass on 11 scenarios, 0 console errors, 0 undefined key leaks

## Business Management (NEW)
Backend collections & endpoints:
- **CRM** — `crm_customers` (name, email, phone, company, position, industry, status: prospect/partnership/existing/ex_client, notes) — CRUD at `/api/portal/admin/crm`
- **Projects** — `projects` (name, customer_name, owner, status, priority, progress %, dates, tasks) — CRUD at `/api/portal/admin/projects`
- **Content planner** — `content_plan` (title, channel, type, status, owner, publish_date, hook, url) — CRUD at `/api/portal/admin/content`
- **Follow-ups** — `followups` (task, customer, channel, due_date, done, owner) — CRUD at `/api/portal/admin/followups`
- **Documents** — `documents` (title, category, customer_name, url, notes) — CRUD at `/api/portal/admin/documents`

Admin sidebar → **Business** group (visible to admin+sales+support depending on module).

## Order → Payment → Deploy flow (visual)
- Client Order page shows a 4-step ribbon at the top: You order → You pay → We verify → Auto provision
- Admin Provisioning page has an "Order → Payment → Deploy" tab with the same 4-step diagram

## Invoice & Quotation PDFs — WHMCS-style (NEW, 2026-02)
Full redesign to match the user's reference `Invoice-615.pdf`:
- Header: real logo top-left + right-aligned PT INTERCLOUD DIGITAL INOVASI address block ending with `NPWP : 62.573.806.7-021.000`
- Diagonal corner ribbon top-right: green **PAID**, amber **UNPAID**, red **OVERDUE**, navy for quotation states (DRAFT/SENT/ACCEPTED/EXPIRED)
- Slate title bar: `Invoice #INV-2026-xxxxx` + long-form `Invoice Date` / `Due Date` (or `Valid Until` for quotations)
- `Invoiced To` panel — pulls from user's billing address (company, ATTN, address_line1/2, city+province+postal, country)
- Simple line-items table (Description | Total). Line description auto-appends `(dd/mm/yyyy - dd/mm/yyyy)` when the item has `period_start`/`period_end`
- Totals block: Sub Total / Tax (11%) / Credit (always shown) / **Total**
- `Transactions` table only when invoice is `paid` — synthesized from `paid_at` + `payment_method` (or from optional `transactions[]` array on the invoice doc). Includes `Balance` row.
- `Payment — Bank Transfer` panel with MANDIRI 1240011911816 and BCA 4730862038 only when `status ∈ {unpaid, overdue}`
- Footer: `PDF Generated on [long date]`

Endpoints:
- `GET /api/portal/documents/invoice/{iid}` → HTML preview (default) with `Print` + `Download PDF` buttons
- `GET /api/portal/documents/invoice/{iid}?format=pdf` → real WeasyPrint-rendered PDF (`application/pdf`, `Content-Disposition: inline; filename="Invoice-INV-xxxx.pdf"`)
- Same two variants for `/documents/quotation/{qid}` (staff-only)

Backend:
- Added `weasyprint==69.0` to `requirements.txt`
- `_pdf_template()` in `routes.py` rebuilt end-to-end to match the reference
- Extended `User` model with optional address block: `attention`, `address_line1`, `address_line2`, `city`, `province`, `postal_code`, `country`, `npwp` (propagated through `UserCreateIn`, `UserUpdateIn`, `UserOut`, `_user_public`, `admin_create_user`, `admin_update_user`)
- Seed backfill: demo client `demo@client.com` now has full billing address + NPWP

Frontend:
- `docUrl(kind, id, format)` in `portal/api.js` — pass `"pdf"` to get real-PDF endpoint
- Admin Invoices / Admin Quotations / Client Invoices tables show two icons: `FileDown` (preview) + `Download` (PDF)
- Admin `New User` modal extended with a full "Billing address" section (ATTN, 2×address, city, province, postal code, country, NPWP)

Tests:
- New pytest module `/app/backend/tests/test_pdf_docs.py` — 8 cases, all green:
  - Client HTML preview + reference layout markers
  - Client PDF download returns real `%PDF-…` bytes with correct Content-Disposition
  - Paid invoice shows PAID ribbon + Transactions table + Balance, and does NOT show bank panel
  - Unpaid invoice shows UNPAID ribbon + Payment—Bank Transfer panel with correct MANDIRI/BCA account numbers
  - Client CANNOT access other users' invoices (403/404)
  - Quotation PDF endpoint + client-forbidden guard
  - `/auth/me` returns the new address fields

## Self-Registration + CRM Auto-Mirror (NEW, 2026-02)
- **Public endpoint** `POST /api/portal/auth/register` — creates a `client` user, hashes password with bcrypt, returns a JWT (auto-login).
- Fields accepted: `email`, `password` (min 8), `name`, `phone`, `company`, full billing address (`attention`, `address_line1/2`, `city`, `province`, `postal_code`, `country`, `npwp`), `industry`, and mandatory `accepts_tos`.
- **CRM auto-mirror**: `_upsert_crm_from_user(db, u, status=…)` is called from BOTH `/auth/register` (`status=prospect`, `source=self_registration`) and `admin_create_user` when role=client (`status=existing`, `source=admin_registered`). Existing CRM rows are refreshed but never downgraded.
- Seed backfill: `demo@client.com` now has a matching CRM row (`source=seed`).
- Frontend: new `/portal/register` page — 2-step form (Account → Billing address), matches login brand style, mandatory TOS checkbox with links to `/legal/terms`, `/legal/aup`, `/legal/sla`, mobile-responsive, includes progress indicator + "Already have an account? Sign in →" back link.
- Login page now has "Don't have an account? Create one →" link right above demo credentials.
- Admin `Business → CRM` table shows a green **"Portal user"** badge next to any contact linked to a portal user (`user_id` set), on hover shows tooltip with source (self_registration / admin_registered / seed / manual).
- Pytest module `/app/backend/tests/test_register_and_crm.py` — 7 cases, all green:
  - Happy path (register → auto-login → CRM row auto-created with correct status/source/user_id)
  - Duplicate email → 409
  - Missing TOS acceptance → 400
  - Weak password → 422
  - Admin-created client → CRM row with `admin_registered` source
  - Admin-created staff (non-client) → NO CRM row created
  - Endpoint requires no auth header (public)

## WHMCS-style Product Catalog + Order Wizard + Admin Access (NEW, 2026-02)

### 1. Refined product catalog
- **Dynamic categories** — new `categories` collection. `GET/POST/PUT/DELETE /admin/categories`, plus public `GET /portal-public/categories`. Categories seed with 10 defaults (cloud/vps/hosting/dedicated/colocation/firewall/interconnect/lease/domain/other). Slug edits cascade to `products.category`. Delete blocked when products still reference the slug (400).
- **Products v2** — extended `ProductIn` with `option_groups`, `is_addon`, `applies_to_product_ids`, `applies_to_categories`, `billing_cycle`, `sort_order`, `stock_qty`. Category field is now free-form string (matches category slug).
- **Option groups** — three types: `dropdown` (radio-style), `checkbox` (0..N), `quantity` (integer input with unit_price_monthly + unit_price_setup). Each dropdown/checkbox option has `price_monthly_delta`, `price_setup_delta`, `is_default`.
- **Add-ons** — products with `is_addon=true`, attach to base products via `applies_to_categories` (OR) `applies_to_product_ids`. Excluded from `/portal-public/products`, listed via new `/portal-public/addons`.

### 2. Order confirmation wizard (Review before Pay)
- New `/orders/preview` endpoint uses shared `_price_cart()` helper → guarantees preview shows the same math as the final invoice.
- Cart breakdown: `base_line`, `option_lines[]`, `addon_lines[]`, `subtotal_monthly`, `setup_total`, `subtotal`, `tax_percent`, `tax_amount`, `total`.
- `POST /client/orders` accepts `selections[]` + `addon_ids[]` + `notes`, snapshots the priced cart on the order (`cart_snapshot` — audit trail), and generates an itemized invoice with one line per option choice and per add-on.
- Client-side `ClientOrder.jsx` rewritten as a 4-step wizard: **Pick a plan → Configure → Add-ons → Review & pay** with a persistent stepper, per-step Back/Continue nav, and a live-priced cart on the Review step. Category tabs auto-hide categories that have 0 orderable products.
- Verified end-to-end: base 100k + 8 GB RAM (+150k) + 2 IPs (2 × 25k) + 50k addon = **Rp 350,000/mo, Rp 388,500 total** (with 11 % tax).

### 3. Admin refinements
- `AdminProducts.jsx` rewritten with filter tabs (All / Base / Add-ons), an `is_addon` toggle that swaps the form between the option-group editor and the applies-to editor, and a nested `OptionGroupEditor` sub-component (dropdown/checkbox/quantity types, option rows with monthly + setup deltas + default checkbox).
- `AdminCategories.jsx` — new page, CRUD for categories with slug auto-sanitising (lowercase, [a-z0-9_-] only), sort order, icon name, is_active.
- `/portal/admin/addons` reuses `AdminProducts` with the Add-ons filter pre-selected via `useLocation`.

### 4. Admin User Access (fine-grained)
- Extended `User` model: `menu_keys?: string[]` (null/empty ⇒ role default), `feature_flags: string[]`, `is_active: bool`.
- New endpoint `GET /admin/user-access-catalog` returns `{menu_catalog:[25 items], feature_flags:[8 items]}` — the canonical registry the admin UI uses to render checkboxes.
- `PortalLayout.jsx` — every admin nav item now carries a `key` matching the catalog. Menu filter respects `user.menu_keys` in addition to `roles`, taking effect in real-time.
- `AdminUsers.jsx` — table has an "Access" column showing badge summaries (menu-count / features-count / assigned-clients-count) and a "Manage access" link that opens `UserAccessModal` with:
  - "Use default for role" toggle
  - Menu checklist grouped by section, showing a "default" badge next to menus the user's role sees by default
  - Feature flags checklist (8 flags)
  - Assigned clients checklist (sales/support only, 28+ clients in demo data)
- Verified real-time: setting `menu_keys=['dashboard','orders']` on a sales user immediately restricts their sidebar to only Dashboard + Orders. Clearing → full default set restored.

### Tests (all green)
- `/app/backend/tests/test_catalog_and_access.py` — 12 cases (categories CRUD, product option-group round-trip, add-on filtering, order-preview pricing, cart snapshot, user access catalog, menu_keys round-trip).
- `/app/backend/tests/test_sprint_extras.py` — 6 cases added by the testing agent (slug cascade, delete-block, /orders/preview auth guard, addon listing, order status + itemized invoice, user access round-trip via list).
- Total sprint coverage: **18/18 pytest green**. Full sweep 66/70 (4 known pre-existing drift failures).
- Frontend E2E: 100% — Order wizard 4 steps all render + advance correctly, admin categories/products/users pages all CRUD, menu_keys sidebar filter works in real time (DOM-verified).

## Finance v2 — Detailed Ledgers + Excel Reports (NEW, 2026-02)
- **Three new expense ledgers** with GET/POST/DELETE CRUD:
  - `kas_kecil` (petty cash) — date/amount/category/vendor/notes
  - `salaries` — date/amount/employee/category/notes
  - `sales_fees` — date/amount/sales_person/invoice_number/notes
- **Month-lock rule** (`_month_locked`): a period YYYY-MM locks as soon as today >= YYYY-(MM+1). Prior years stay locked except during a Jan 1-5 amendment window. Insert/delete on locked months → 403 with a human-readable message.
- **Detailed report** `GET /admin/finance/detailed` — paid-invoice rows + 4 expense ledgers + asset rows (book value + accum. depreciation) + `totals` object (revenue / expenses_recurring / kas_kecil / salaries / sales_fees / expenses_all / depreciation_accumulated / net_profit).
- **Monthly Excel** `GET /admin/finance/report/monthly/YYYY-MM` → 6-sheet .xlsx (Summary / Revenue / Expenses / Kas Kecil / Salaries / Sales Fees). Uses openpyxl. Auto-frozen into `finalized_reports` on every generation.
- **Annual Excel** `GET /admin/finance/report/annual/YYYY` → 3-sheet workbook: P&L (12 months + cumulative columns), Assets, Revenue detail.
- **Audit log** `GET /admin/finance/reports` — every generated report with a `locked` badge.
- **Frontend** `AdminFinance.jsx` — 8-tab UI (Summary / Revenue / Expenses / Kas Kecil / Salaries / Sales Fees / Assets / Reports), 4 KPI cards (Net Loss turns red), header quick-downloads for this month + this year. Shared `LedgerPane` sub-component. Reports tab has 12-month download grid + 3-year annual tiles + audit-log table.
- **Tests**: `/app/backend/tests/test_finance_v2.py` — 10 cases all green.
- Verified end-to-end (iteration_11) — all pytest passes on both internal and preview URLs, xlsx opens in openpyxl with correct sheet structure, UI add/delete/download flows all confirmed.


## Unified Integrations + IMAP (NEW, 2026-02, latest)

**User request**: merge the two separate menus ("Integrations" WHMCS-style + "Real APIs") into one page; add IMAP for inbound email alongside SMTP; update all logic/menu/features accordingly.

### Backend
- `integrations_v2.INTEGRATION_SCHEMA` extended:
  - New providers: **imap**, **cpanel**, **plesk**
  - Every provider now has `category` (virtualization / network / provisioning / payment / mail) and a human `description`.
- New `IMAPClient` class in `integrations_v2.py` — `test_connection()` and `fetch_recent(limit)` using `imaplib.IMAP4_SSL`, best-effort text/plain body extraction.
- `/admin/integrations-v2/{provider}/test` extended to route **smtp**, **imap**, **cpanel**, **plesk** — all return graceful `ok:false` on failure (never 500).
- New `DELETE /admin/integrations-v2/{provider}` — wipes settings cleanly (PUT merges secrets by design; DELETE is needed for rotation).
- `/admin/mail/inbox` — prefers **live IMAP** when enabled + reachable; falls back to seeded demo messages on error.
- `/admin/mail/send` — prefers **v2 SMTP** when enabled; falls back to legacy v1 `integrations` collection or logs `delivered_via='queued (SMTP not configured)'`.
- `ADMIN_MENU_CATALOG` — removed key `real_integrations`. `integrations` (single unified) retained.

### Frontend
- **`AdminIntegrations.jsx` rewritten from scratch** as a unified category-grouped page:
  - 3 mini-stat cards: providers configured / categories / legacy modules count
  - Legacy migration hint auto-shown when old `integrations` collection still has rows
  - Category-grouped provider cards (Virtualization / Network / Provisioning / Payments / Mail)
  - Each card expands to reveal credentials + options + Test/Save (with data-testids)
- **`AdminRealIntegrations.jsx` deleted**; `/portal/admin/real-integrations` `<Navigate>` redirects to `/portal/admin/integrations`.
- **PortalLayout** — Real APIs entry removed from the System group; unused `Zap` icon import cleaned up.
- **AdminMail** — SMTP-missing banner now inspects **both** v1 (`/admin/integrations`) and v2 (`/admin/integrations-v2`) for SMTP or IMAP; wording updated to "SMTP + IMAP not configured".

### Tests
- `/app/backend/tests/test_integrations_unified.py` — **13 new pytest cases green**: schema shape + categories, IMAP save/mask, IMAP graceful test failure, cPanel missing/complete validation, Plesk validation, SMTP now wired, menu-catalog no longer has `real_integrations`, mail inbox fallback, DELETE endpoint.

**Total backend tests: 117/117 green on all modules touched by this refactor** (2 pre-existing drift failures in `test_portal.py` unrelated to this change — same as pre-session baseline).

## Password Lifecycle + Real Integrations Scaffold (NEW, 2026-02)
- `POST /auth/change-password` — self-service (client + all staff)
- `POST /admin/users/{uid}/reset-password` — admin-only, optional SMTP notification
- `POST /auth/forgot-password` — public, no-enumeration, 60-min single-use token stored sha256-hashed
- `POST /auth/reset-password` — public, single-use token consumption
- Frontend: `/portal/forgot-password`, `/portal/reset-password?token=…`, `/portal/{admin|client}/settings/password`

### Real integrations scaffold (Option A — code-complete, drop-in creds later)
- `portal/integrations_v2.py`: ProxmoxClient, MikrotikClient, Midtrans/Xendit/DuitkuGateway, SMTPMailer — all read secrets from `integration_settings`
- Admin UI at `/portal/admin/real-integrations` — 6 collapsible provider cards with test-connection + save
- Signature verification enforced BEFORE any state mutation on webhooks

### Route guard fix
- `RequireAuth` supports `role="staff"` (or array); admin URLs redirect clients to `/portal/client/dashboard`

## Automated Email & Notification Engine (NEW, 2026-02)

### Backend
- New `portal/emails.py` module: 12 seeded system templates (welcome, order_confirmation, invoice_generated, invoice_reminder_d3, invoice_due, invoice_overdue_d1/d3/d7, service_suspension, password_reset, maintenance, newsletter). Variable renderer supports `{{user.name}}`, `{{invoice.number}}`, `{{invoice.total_fmt}}`, `{{invoice.due_date}}`, `{{portal.login_url}}`, `{{portal.invoice_url}}`, `{{order.product_name}}`, `{{reset_url}}`, `{{maintenance.title}}`, `{{month.name}}`, etc.
- **Refined language & real Intercloud logo** in the email wrapper (Feb 2026 refresh, `_SEED_VERSION=2`): every system template rewritten in polite, professional English. Auto-refresh on startup for templates whose `send_count==0`, so admin edits are never overwritten.
- **Event hooks** fire instant emails: `/auth/register` → welcome; `/client/orders` → order_confirmation + invoice_generated; `/admin/users` (role=client) → welcome.
- **APScheduler** (Asia/Jakarta, hourly at :05 + on-startup) runs `run_invoice_reminder_sweep` — scans unpaid/overdue invoices, matches `delta_days` to offset templates (-3, 0, +1, +3, +7, +8), and on D+8 flips linked active services to `suspended`. Idempotent per (invoice, event, day) via `_sent_today` guard.
- **Admin endpoints** (`/api/portal/admin/...`):
  - `GET/POST/PUT/DELETE /email-templates` (system templates protected from delete; event_key immutable)
  - `POST /email-templates/preview` — sample rendering with substituted variables
  - `POST /email-templates/send-test` — sends a rendered test email to any address
  - `POST /email/broadcast` — audience: `all_clients` / `all_users` / `custom`
  - `POST /email/run-scheduler-now` — manual sweep trigger
  - `GET /email-logs` — audit trail (status, delivered_via, error, timestamps)
  - `GET /email/event-catalog` — canonical event + variable registry
- **Delivery**: uses existing `SMTPMailer` from `integrations_v2`. When SMTP is disabled every send logs with `status='skipped'` + `delivered_via='log'` (never crashes).

### Frontend
- New `AdminEmails.jsx` (3-tab UI: Templates / Broadcast / Delivery log)
  - Templates: table of all events with trigger badge + offset · time + Active toggle + Sent count; per-row Preview (modal iframe) + Edit (full editor: subject, body HTML, offset days, send time HH:MM, notes, active); "Run scheduler now" button; "New template" for custom events; system templates non-deletable.
  - Broadcast: audience selector (all_clients / all_users / custom emails), subject, body HTML, live results (recipients / sent / failed / skipped).
  - Delivery log: filter chips (all/sent/failed/skipped), reverse-chrono table with event / recipient / subject / status / error.
- Menu key `email` (label "Email Automation") wired in sidebar + `ADMIN_MENU_CATALOG`.

### Tests
- `/app/backend/tests/test_emails.py` — **19 pytest cases green**: seed correctness + offset_days validation, CRUD, event_key immutability, system-delete protection, duplicate 409, preview with variables, raw preview, send-test with SMTP-disabled, RBAC 403, register + order + invoice-generated hooks fire, D-3 reminder sweep, D+8 suspension side-effect (service flipped to `suspended`), idempotency, broadcast custom / all_clients / empty→400.

## Articles / CMS Module (NEW, 2026-02)

### Backend
- New `articles` collection: title, slug, excerpt, body_html, cover_image_url, video_url, author_name, tags[], category, status (draft/published/archived), published_at, meta_title, meta_description, meta_keywords[], og_image_url, is_featured, view_count.
- Endpoints:
  - Admin (staff): `GET /admin/articles`, `GET /admin/articles/{aid}`, `POST /admin/articles`, `PUT /admin/articles/{aid}`, `DELETE /admin/articles/{aid}`, `GET /admin/articles-tags` (aggregated counts).
  - Public: `GET /public/articles` (with `q` full-text search + `tag` filter + pagination), `GET /public/articles/tags`, `GET /public/articles/{slug}` (auto-increments view_count + returns 3 related).
- Slug auto-generated from title; collisions auto-suffix `-2`, `-3`. Tags normalised to lowercase kebab-case + deduped. `published_at` auto-stamped on first publish. Text index on title/excerpt/body/tags (`articles_text_idx`). Draft articles NOT visible on public endpoints.
- 3 demo articles seeded (Insight / Guide / Announcement).

### Frontend
- New `AdminArticles.jsx` — full CRUD table with search + status filter + tag filter. Editor modal with 3 sub-tabs:
  - **Write** — title, slug (optional), category, excerpt, HTML body with a mini toolbar (H1/H2/Bold/Italic/List/Quote/Link/Image via prompts).
  - **Media** — cover image URL (live preview), video URL (auto-embed for YouTube/Vimeo, `<video>` for MP4).
  - **SEO & Tags** — tags (comma-separated), meta title, meta description, meta keywords, OG image URL.
  - Sidebar: status selector (draft/published/archived), author override, featured toggle, live preview card.
- New public pages:
  - `/articles` (`ArticlesList.jsx`) — navy hero with search, tag chips facet, featured card, responsive grid of article cards. Search + tag chips update URL params.
  - `/articles/:slug` (`ArticleDetail.jsx`) — full SEO stack (title, meta description, meta keywords, OG title/description/image/type, article:published_time, article:tag[], Twitter card, canonical link, JSON-LD `BlogPosting` script). Article body uses `@tailwindcss/typography` prose classes. Auto-embeds YouTube/Vimeo/MP4 videos. Tags link back to `/articles?tag=…`. Related articles section. Share button (Web Share API + clipboard fallback).
- Header (public): new "Articles / Artikel" nav link (data-testid=header-articles-link).
- Sidebar (admin): new "Articles" item under Support & CRM (menu key `articles`, roles admin/sales/support).

### Tests
- `/app/backend/tests/test_articles.py` — **12 pytest cases green**: seed visible, search, tag facet, tag filter, view-count increment, related, 404, draft-not-public, create→publish→delete happy path, RBAC 403 for clients, slug collision suffix, admin search+status filter.

## Testing status (2026-02)
- Latest run (iteration_13): **35/35 backend pytest green** + all frontend E2E green (100%).
- Only non-blocking finding: a React hydration warning `<p> cannot be a child of <span>` inside the admin editor Select — cosmetic, no functional impact.


### Password lifecycle
- `POST /auth/change-password` — self-service (client + all staff), rejects wrong current pw, same-password, weak (<8) via Pydantic
- `POST /admin/users/{uid}/reset-password` — admin-only, optional `notify_user` SMTP notification
- `POST /auth/forgot-password` — public, no-enumeration neutral response, 60-min single-use token stored sha256-hashed. SMTP fallback logs the raw link to `/var/log/supervisor/backend.err.log` when SMTP is disabled
- `POST /auth/reset-password` — public, single-use token consumption
- Frontend: `/portal/forgot-password`, `/portal/reset-password?token=…`, `/portal/{admin|client}/settings/password`, plus a lock-icon quick-link in the sidebar user card, plus a per-row "Reset pw" button in Admin Users with a confirmation modal

### Real integrations scaffold (Option A — code-complete, drop-in creds later)
- New `portal/integrations_v2.py` with adapter classes: `ProxmoxClient` (async httpx + token auth), `MikrotikClient` (librouteros), `MidtransGateway` / `XenditGateway` / `DuitkuGateway` (with signature verification), `SMTPMailer`. All read secrets from the `integration_settings` collection
- Admin UI at `/portal/admin/real-integrations` — 6 collapsible provider cards (Proxmox / Mikrotik / Midtrans / Xendit / Duitku / SMTP), each with Enabled toggle + Credentials block (with `saved: xxxx****` placeholder for stored secrets) + Options + Test-connection + Save
- Live-action endpoints wired: `/admin/proxmox/{nodes,vms,vms/{node}/{vmid}/{action},vnc}`, `/admin/mikrotik/{interfaces,bgp,traffic}`, plus `/client/invoices/{iid}/pay-online?provider=…` and public `/webhooks/{provider}`. All return 400 with "not configured" until the corresponding integration is enabled
- Signature verification enforced BEFORE any state mutation on webhooks (bogus sig → 400, never 200)

### Route guard fix (post-agent-review)
- `RequireAuth` now supports `role="staff"` (or an array of allowed roles); `/portal/admin/*` gate updated so a client that navigates directly to an admin URL is redirected to `/portal/client/dashboard` instead of seeing a React dev-overlay

### Tests (all green — 56/56 sprint + regression)
- `test_real_integrations.py` — 9 tests (schema, list+upsert+masking, unconfigured behaviour, unknown provider 404, live-action gating, pay-online guard, webhook signature)
- `test_password_lifecycle.py` — 11 tests (self-change: happy + 3 rejection paths, admin reset, client-cannot-reset-others, forgot no-enumeration, one-shot reset token, bad-token)
- Provisioning → Proxmox tab lists 9 seeded OS templates from Proxmox ISO storage (`GET /api/portal/admin/proxmox/os-templates`)
- "OS not listed? Request one →" button opens a modal that files a technical ticket via `POST /api/portal/client/proxmox/os-request`
- Admin can override the OS template list via `PUT /api/portal/admin/proxmox/os-templates`

## DCIM & IPAM — now native (NOT an integration)
- Removed `dcim` from `MODULE_SCHEMAS` — integrations list is now 10 modules (cpanel/plesk/proxmox/mikrotik/duitku/xendit/midtrans/smtp/whois/blacklist)
- Native DCIM endpoints: `GET/POST /api/portal/admin/dcim/racks|prefixes` with auto-seeded demo racks & prefix pools
- Rack view shows per-U occupancy, customer tagging, and power draw bar (green/red)
- P1: Backend contact form (MongoDB) — capture name/company/service/message
- P2: Blog / case-studies section
- P2: Data-center virtual tour section (video / 360)
- P2: Bandwidth/pricing calculator widget
- P2: Client testimonials / logo carousel with quotes
- P2 (tech-debt): Consolidate WA-message templates in Services.jsx / Pricing.jsx to use `wa.prefilled.svc` / `wa.prefilled.plan` from LanguageContext dict


## Straight-Line Depreciation Rewrite (2026-07-22) — Phase 1 ✅
**Confirmed direction:** Rewrite Admin Assets depreciation to metode garis lurus.
**Formula:** `Penyusutan per Tahun = (Harga Perolehan − Nilai Sisa) / Umur Ekonomis`

### Backend (`/app/backend/portal/routes.py` §2372-2610)
- `_asset_depreciation(a)` returns full snapshot: annual/monthly/accumulated_depreciation, book_value (floored at salvage), months_elapsed, total_months, is_fully_depreciated, depreciable_base
- `_asset_book_value(a)` and `_asset_schedule(a)` derive from it; `_serialize_asset` exposes all fields
- New `_coerce_asset_payload` normalizes incoming payloads (backward-compat: derives `useful_life_years` from `useful_life_months` ÷ 12, or `depreciation_percent` → `round(100 ÷ pct)`)
- New endpoint: `GET /api/portal/admin/assets/{id}` — returns asset + `schedule[]` (yearly rows for the full life)
- Fields added to schema: `salvage_value`, `useful_life_years` (legacy `depreciation_percent` + `useful_life_months` still accepted)
- `finance_detailed` + annual xlsx now emit `salvage_value`, `useful_life_years`, `annual_depreciation` columns

### Startup migration (`/app/backend/portal/seed.py`)
- `_migrate_assets_straight_line(db)` backfills `salvage_value=0` on any pre-existing doc missing it and derives `useful_life_years` from legacy fields

### Frontend (`/app/frontend/src/pages/portal/admin/AdminAssets.jsx`)
- New form fields: Salvage / Nilai Sisa, Useful Life / Umur Ekonomis (tahun)
- **Live preview** panel showing Depreciable Base + Annual + Monthly as user types
- New **Schedule modal** (Calculator icon per row) with yearly breakdown
- Table columns updated: Cost, Salvage, Life, Annual Dep., Book Value (with -Accumulated hint)
- `AdminFinance.jsx` assets tab table updated to include Salvage / Life / Annual Dep.

### Validation
- Test case (value=10M, salvage=1M, life=5y, purchase=2020-01-01): annual=1.800.000, monthly=150.000, accumulated=9.000.000, book=1.000.000 (salvage floor), fully depreciated ✅
- Backend tests: **24/24 pytest pass** (14 new straight-line tests + 10 existing finance_v2 tests still green)
- Test file: `/app/backend/tests/test_assets_straight_line.py`

## Backlog (from continuation plan)
- Phase 2: CAPTCHA — Cloudflare Turnstile placeholder in portal login/register/forgot (skip until user provides site+secret keys)
- Phase 3: Bug fixes & refactor pass (routes.py 4500 lines → split per-domain)
- Phase 4: Performance — MongoDB indexes on hot queries, frontend lazy routes
- Phase 5: UI/UX polish, accessibility
- Phase 6: QA & handover


## Google reCAPTCHA v3 (2026-07-22) — Phase 2 ✅ (feature flag OFF, keys pending)
**Ganti dari Cloudflare Turnstile** ke Google reCAPTCHA v3 (score-based, invisible) untuk portal Login/Register/Forgot-Password. Tersedia sebagai provider baru di menu **Integrations**.

### Backend
- `INTEGRATION_SCHEMA['recaptcha']` di `integrations_v2.py` — category='security', credentials `{site_key, secret_key}`, options `{min_score(=0.5), expected_hostname, verify_action(=true)}`
- `class RecaptchaV3Verifier` — async `verify(token, action, remote_ip)` panggil Google siteverify, cek `success`+`action`+`hostname`+`score>=min_score`, raise HTTPException 400/403
- Helpers `get_recaptcha_settings(db)` + `enforce_recaptcha(db, token, action, ip)` — no-op saat disabled
- Auth endpoints (`/auth/login`, `/auth/register`, `/auth/forgot-password`) sekarang `await iv2.enforce_recaptcha(...)` sebelum cek password
- Endpoint public baru `GET /api/portal/auth/config` — hanya expose `{recaptcha:{enabled, site_key}}`, **secret_key tidak pernah dikirim**
- Models `LoginIn/RegisterIn/ForgotPasswordIn` tambah `recaptcha_token: Optional[str] = None` (backward-compat: klien lama tanpa field ini tetap 200 saat feature disabled)

### Frontend
- `src/portal/recaptcha.js` — lazy fetch `/auth/config`, inject Google script sekali, `getRecaptchaToken(action)` return token atau null bila disabled
- `AuthContext` login/register auto-attach token
- `PortalForgotPassword` juga wire ke reCAPTCHA (action=`forgot`)
- Badge "Protected by Google reCAPTCHA v3 — Privacy/Terms" muncul di login saat enabled
- `AdminIntegrations` UI menambah kategori **Security & Anti-bot** + kartu Google reCAPTCHA v3 dengan icon ShieldCheck

### Test coverage
- `/app/backend/tests/test_recaptcha_auth.py` — **13/13 pass** (schema, PUT persistence + secret masking, fail-open, missing token, garbage token, config exposes site_key only, disable-again, backward-compat)
- Existing suites (straight-line assets, finance_v2) tetap hijau — no regression

### Aktivasi (kapan user mau)
1. Ke `https://www.google.com/recaptcha/admin/create` → pilih **v3** + domain
2. Copy Site Key + Secret Key
3. Portal Admin → **Integrations** → **Google reCAPTCHA v3** → Enabled + isi keys + Save
4. Selesai. Login/Register/Forgot langsung protected tanpa deploy ulang.


## Login Attempt Analytics (2026-07-22) — Security Dashboard ✅
Follow-on setelah reCAPTCHA integration. Log setiap `/auth/login` (success + failure) ke koleksi `login_attempts` untuk visibilitas bot & brute-force.

### Backend
- Helper `_log_login_attempt()` di `portal/routes.py` (~L118) — insert best-effort, tidak pernah raise ke caller
- `/auth/login` rewritten untuk log setiap attempt dengan: email, action, success, reason, ip, user_agent, recaptcha_enabled, recaptcha_score
- Reason codes: `ok`, `invalid_credentials`, `recaptcha_missing`, `recaptcha_failed`, `recaptcha_low_score`
- Endpoint baru `GET /api/portal/admin/security/login-analytics?window=24h|7d|30d&limit=N` (admin-only) — return totals + reason_breakdown + top_ips + top_emails + hourly/daily series + reCAPTCHA score histogram + recent list
- MongoDB indexes ditambah di `server.py`: `login_attempts.created_at`, `.email`, `.ip`

### Frontend
- Page baru `/app/frontend/src/pages/portal/admin/AdminSecurity.jsx` — dashboard lengkap:
  - Window switcher: 24h / 7 days / 30 days
  - 4 KPI cards: Total Attempts, Success Rate, Failed, Blocked by reCAPTCHA
  - Line chart "Attempts over time" (Success / Failed / reCAPTCHA per bucket)
  - Bar chart "reCAPTCHA score distribution" (0.0–1.0 buckets)
  - Top offending IPs + Top targeted emails tables
  - "Outcome breakdown" pill row
  - Recent attempts table (Time, Email, Action, IP, Outcome badge, reCAPTCHA score)
- Route `/portal/admin/security` di `App.js`, sidebar entry "Security" dengan icon ShieldCheck di grup System

### Test coverage
- `/app/backend/tests/test_login_analytics.py` — **13/13 pass** (RBAC, success/failure aggregation, reCAPTCHA-blocked logging, window buckets, score histogram, limit cap)
- Existing suites tetap hijau: `test_recaptcha_auth.py` (13), `test_assets_straight_line.py` (14)

### Future improvements (dari code-review agent)
- (Non-blocking) Refactor `portal/routes.py` sudah 4700+ baris → split per-domain module
- (Nice-to-have) Enforce `?window=` strictly (currently unknown value falls into daily branch), atau map fallback ke 24h konsisten
- (Non-blocking) Beralih ke MongoDB aggregation pipeline saat traffic besar (saat ini in-memory sampai 20k rows)


## Real Diagnostic Tools + Auto-Block IP + MikroTik Torch (2026-07-22) ✅

Replaced all mock diagnostic outputs with **real** network commands, added an auto-block IP feature, and integrated MikroTik `/tool/torch` via the existing librouteros integration.

### Diagnostic Tools (real, sandboxed)
- **New module** `/app/backend/portal/diagnostics.py` with strict input validation and hard timeouts
- Tools available: `ping` (via `ping3` python lib — no root), `traceroute`, `dns` (dig, all record types), `whois`, `blacklist` (8 DNSBLs: Spamhaus/SpamCop/SORBS/Barracuda/UCEPROTECT/PSBL/Manitu/SpamRats), `portscan` (20 common TCP ports), `http` (real GET + headers/body preview), `torch` (MikroTik `/tool/torch`)
- Endpoint `POST /api/portal/admin/diagnostics/run` (admin) with per-tool extra kwargs
- Endpoint `GET /api/portal/admin/diagnostics/tools` — advertises available tools + `mikrotik_ready` so UI can grey out unavailable tools
- Frontend `AdminDiagnostics.jsx` fully rewritten: tool picker card grid, dynamic form fields per tool, KPI summary tiles, terminal-style output, real-time flows table for torch, copy-to-clipboard

### MikroTik Torch
- New method `MikrotikClient.torch(interface, duration, src_address, dst_address, protocol, port, ip_version)` in `integrations_v2.py`
- Torch calls `/tool/torch` on the configured RouterOS with a bounded duration (1–10s), returns sorted flow rows (proto, src/dst address+port, tx/rx rate, packet counts)
- Frontend form pulls interface list from `/admin/mikrotik/interfaces` dropdown, sends filters, renders result table

### Auto-Block IP
- 10 failed logins in 15 min from same IP → auto-block 30 min (all configurable)
- Guard `_is_ip_blocked()` at top of `/auth/login` returns HTTP 429 for blocked IPs
- Endpoints:
  - `GET/PUT /api/portal/admin/security/settings` — thresholds config
  - `GET /api/portal/admin/security/blocked-ips[?active_only=true]`
  - `POST /api/portal/admin/security/blocked-ips` — manual block
  - `DELETE /api/portal/admin/security/blocked-ips/{ip}` — manual unblock
  - `GET /api/portal/admin/security/notifications` + `POST .../mark-read`
- New collections `blocked_ips` + `security_notifications` with proper indexes

### Test coverage
- `/app/backend/tests/test_diagnostics_and_security.py` — 20 tests (all 8 tools, auto-block flow, RBAC, torch validation/happy-path)
- **60/60 tests green** across 4 files (recaptcha, login-analytics, assets, diagnostics)

### Critical fix during testing
- `_is_ip_blocked` + `_maybe_auto_block` + `blocked_ips_list` had a tz-naive vs tz-aware datetime comparison bug (MongoDB returns naive UTC even when tz-aware written) → 500 on 11th failed login. Testing agent normalized all datetime reads to offset-aware UTC. Verified.

### Dependencies added
- `ping3` (pip) — pure-python ICMP without root
- `iputils-ping`, `traceroute`, `whois`, `dnsutils` (apt)
