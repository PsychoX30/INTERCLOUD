# Intercloud Portal — Product Requirements Document

React + FastAPI + MongoDB ISP/Cloud Provider admin portal with live MikroTik integration.

## Original problem statement
Enterprise-ready admin portal for ISP/DC operator "Intercloud Digital Inovasi"
with role-based access, per-admin email, PDF invoices, MikroTik live ops,
UAT-compliant security, self-installer for Ubuntu 24.04 Proxmox VMs.

## Implemented (as of 2026-07-23 — batch 4)

### Batch 4 — Per-user SMTP send + Sales scoping expansion (this session)
- **P0** `POST /api/portal/admin/mail/send` now uses the caller's own
  `users.email_settings.smtp` — no more global iv2 SMTP fallback. Returns
  HTTP 400 with `"Silakan setup SMTP dulu di Settings ▸ Email…"` when
  personal SMTP isn't configured. Actual SMTP send errors surface as 502
  (previously silently marked "queued").
- **P1** New helpers `_sales_scope_filter()` and `_sales_visible_crm_ids()`
  in `routes.py` — single source of truth for Sales scoping filters.
- **P1** Applied Sales scoping to:
  - `GET /admin/invoices` — role switched from admin→staff, filter by user_id∈assigned
  - `GET /admin/crm` — filter by user_id∈assigned
  - `PUT/DELETE /admin/crm/{id}` — 403 if sales tries to touch another rep's client (`_assert_sales_can_touch_crm`)
  - `GET /admin/followups` — filter customer_id to sales-visible CRM rows
  - `POST /admin/followups` — 403 if creating for a non-assigned customer
  - `PUT/DELETE /admin/followups/{id}` — 403 if sales tries to touch another rep's follow-up
- **P2** DataTable rolled out to `AdminQuotations`, `AdminProducts`,
  `AdminCategories`, `AdminTickets` (sort, search, empty state, skeleton).
- **P1** New `iv2.IMAPConnectionError` — `IMAPClient.fetch_recent` now
  distinguishes connect/auth failures (raises) from an empty inbox
  (returns `[]`) and per-message parse errors (skipped). `admin_mail_inbox`
  surfaces `{not_setup:true, reason:"connection_failed", detail:…}` with the
  underlying diagnostic instead of a silent empty inbox. `admin_mail_message`
  now returns 502 on IMAP connection failure.
- **SEO polish**: `ArticleIn.cover_image_alt` added (Pydantic + serializer +
  `AdminArticles` editor field). Frontend `ArticlesList` and `ArticleDetail`
  use `cover_image_alt || title` for every `<img alt=…>`. SVG favicon +
  apple-touch-icon shipped in `/frontend/public/`, wired into `index.html`
  (mask-icon + rel=icon type=image/svg+xml).
- Regression suites:
  - `/app/backend/tests/test_sales_scoping.py` — 9 tests (invoices/CRM/followups scoping + admin sees-all + mail-send 400)
  - `/app/backend/tests/test_imap_and_seo.py` — 6 tests (IMAP raise vs empty, no_credentials vs connection_failed, cover_image_alt round-trip, favicon + apple-touch-icon served)

### Batch 3 — F1 Per-admin email + F3 Sales scoping (iter30 15/15 pass)
- Every staff member configures own cPanel IMAP/SMTP creds via
  `POST /api/portal/settings/email`. Stored on `users.email_settings`.
  `_mask_email_settings` redacts BOTH imap + smtp passwords on GET responses.
- `admin_mail_inbox` uses caller's own IMAP; returns `{not_setup:true,...}`
  when unconfigured. Frontend AdminMail.jsx shows amber "Belum di-setup"
  card + 8-input setup modal.
- `admin_dashboard` scopes stats via `assigned_client_ids` for role=sales.
  Finance role now sees full financial fields (revenue_month/total,
  overdue_total, unpaid/overdue counts).

### Batch 2 — Bug trio (iter29 21/21 pass)
- B1 Mail: `imap-*` prefix + invalid ObjectId handled gracefully (404/400).
- B2 Sales stuck loading: `/admin/orders` + `/admin/quotations` use
  `get_current_staff` with `{"user_id":{"$in":assigned}}` filter.
- B3 Dashboard "undefined invoice(s)": frontend `${s.overdue_invoices||0}`.

### Batch 1 — Role catalog + Finance role (iter28+29 baseline)
- ADMIN_MENU_CATALOG: 30 items with tightened default_roles per user
  spec (finance can see billing/customers/reports, sales only assigned
  clients + shared menus, support only technical menus).
- FEATURE_FLAG_CATALOG: 23 flags across Delete/Financial/Ops/System/CRM.
- New `finance` role: STAFF_ROLES + FINANCE_ROLES + models Literal types
  + AdminUsers.jsx dropdown + purple badge.

### UAT Fixes (iter28)
- C1 Sitemap XML: nginx `/sitemap.xml` proxy to `/api/portal/sitemap.xml`.
- C2 Security headers: nginx template writes X-Frame-Options DENY,
  X-Content-Type-Options nosniff, Referrer-Policy, Permissions-Policy,
  CSP (hardcoded string, no `map` directive), COOP. HSTS auto by certbot.
- C3 404 route: `<Route path="*">` + NotFound.jsx with meta robots noindex.
- M1 nginx version: `/etc/nginx/conf.d/00-hardening.conf` with
  `server_tokens off`.
- robots.txt inline in nginx (Disallow: /portal/admin).

### Branding
- `_DEFAULT_LOGO_LIGHT` and `_DEFAULT_LOGO_DARK` load bundled webp files
  from `/app/backend/portal/assets/*.webp` as inline data URIs — real
  Intercloud artwork ships with the repo (light 99KB, dark 204KB).
- Landing header/footer logo sized `h-16 md:h-20` (80px desktop), header
  container `h-[96px]`. PDF invoice logo `height:130px`.

### System Ops
- Factory Reset `POST /api/portal/admin/system/factory-reset` (admin only,
  double-guarded, preserves settings + admins, takes safety snapshot).
- Landing CMS via `settings` collection `key=landing_content`.
- Backup/Restore via `mongodump`/`mongorestore` subprocess.
- Daily backup cron `/etc/cron.d/intercloud-daily-backup`.

## `install.sh` (Ubuntu 24.04 auto-installer)
Defaults baked in:
- REPO_URL `https://github.com/PsychoX30/INTERCLOUD.git`
- PORTAL_DOMAIN `intercloud-digital.com`
- LETSENCRYPT_EMAIL `support@intercloud-digital.com`
- ADMIN_EMAIL `support@intercloud-digital.com`
- ADMIN_PASSWORD `AdminIntercloud2026!`
Includes: AVX preflight (blocks non-AVX CPU → MongoDB SIGILL), MongoDB
8.0 for Noble / 7.0 for Jammy, auto-recovery of stale mongo auth state,
git reset --hard on re-runs, extra-index for emergentintegrations, DNS
preflight before certbot, verbose certbot with fail-loud, robust nginx
template (no `map` directive), `/var/www/html/.well-known/acme-challenge`
webroot pre-created, `server_tokens off`.

## Roadmap / Backlog
- **P2** DataTable rollout to remaining screens (AdminOrders, AdminMikrotik).
- **P2** Zod + react-hook-form inline validation on Login/Register/ForgotPassword.
- **P2** Factory-reset snapshot retention (keep last 5).
- **P3** react-snap prerender for SPA landing (needs puppeteer; Googlebot
  already handles the client-side meta but some crawlers don't).
- **P3** Phase 6 QA & Handover smoke test across all modules.
- **P3** Full SSR (Next.js migration) for UAT M3 SEO parity.

### Batch 5 — Webmail compose fix + Test Connection (2026-07-24)
- **Bug fixed**: Compose modal in `AdminMail.jsx` was a static placeholder claiming
  "SMTP belum di setup" even when SMTP worked. Replaced with a real ComposeModal →
  `POST /admin/mail/send` (to/subject/body, success state, 400 error links to Setup modal).
- **New endpoint** `POST /api/portal/settings/email/test` — tests IMAP + SMTP using
  existing `IMAPClient.test_connection()`/`SMTPMailer.test_connection()`. Same payload
  shape as save; masked "••••••••" passwords fall back to stored via shared
  `_merge_email_payload()` helper (refactored out of the save endpoint, save behavior unchanged).
  Returns `{ok, imap:{ok,message}, smtp:{ok,message}}`; wrong creds → 200 ok:false (never 5xx).
- **Test Connection button** in SetupEmailModal with green/red per-protocol result rows.
- Regression suite: `backend/tests/test_mail_test_connection.py` (6 tests, all pass,
  uses live mailbox damien@intercloud-digital.com — see memory/test_credentials.md).
- Verified end-to-end: compose → delivered_via=smtp → message visible in IMAP inbox.

### Batch 8 — Phase 4 Executive Visibility + Public Status Page (2026-07-24)
- **`owner` role**: added to STAFF_ROLES + FINANCE_ROLES + Literal role validators.
  Owner is READ-ONLY globally — can view Executive Overview dashboard but every write
  endpoint refuses with 403 (owner not in admin/staff-mgmt roles). ProtectedRoute
  frontend also whitelists 'owner' inside `isStaff` so /portal/admin routes are
  reachable.
- **Executive Overview** `GET /admin/owner/overview` (owner+admin only): aggregates
  MRR (Σ active-service.price_monthly), ARR (MRR×12), ARPU (MRR / clients-with-active),
  Churn% (terminated last 30d / total), revenue MTD, 12-month revenue trend series,
  outstanding & overdue totals, NOC uptime 24h/7d (from `noc_probes`), outage minutes
  30d, ticket load, and top-5 clients by lifetime revenue. Frontend
  `AdminOwnerDashboard.jsx` renders 8 KPI tiles + recharts LineChart (revenue trend)
  + BarChart (invoice volume) + awarded top-clients list. Sidebar entry under
  Overview group (roles: admin, owner).
- **Public Status Page** at `/status` (no auth): `GET /public/status` aggregates
  `noc_probes` by abstract `status_group` bucket ("Core Network" / "Customer Edge" /
  "Peering & Transit" by default — configurable). NEVER leaks device names, IPs,
  or topology. Overall status: degraded ⚫ operational ⚫ unknown (uses "unknown" if
  no groups have data). Auto-refresh every 60s. Admin config UI at
  `/portal/admin/status-page` with company name, incident banner, and group editor
  (add/remove/rename). All changes recorded to audit_logs
  (`status_page.config_update`).
- **Testing iter 32**: PASSES ALL — AdminMail Reply bug retest confirmed FIXED,
  Executive Overview KPIs + charts + top-clients all render, /status returns
  anonymised group data (verified against raw JSON — no device leakage), owner
  role gets 403 on all write endpoints, incident banner appears when configured.
  Only OPTIONAL cosmetic recharts warning also fixed via explicit min-height.

### Batch 7 — Phase 1 Audit Log + Phase 2 Credit Notes + Phase 3 NOC Monitor (2026-07-24)
- **Audit Log** (`portal/audit.py`): fire-and-forget `log_audit(db, ...)` helper writes
  to `audit_logs` collection with actor/target/before/after/ip/user_agent + auto-redacts
  secret-ish fields (password, api_key, token, …). Instrumented endpoints: user
  role/password change, user delete, admin password reset, billing settings update,
  security settings update, integration upsert/delete, factory reset, backup restore,
  credit-note create/apply/cancel, invoice.settled_by_credit. New endpoints
  `GET /admin/audit-logs` (paginated + filters: category/action/actor/severity/date/q)
  and `GET /admin/audit-logs/facets`. Frontend `AdminAuditLog.jsx` with DataTable-style
  layout, filters, and before/after JSON detail modal.
- **Credit Notes** (`credit_notes` collection): CN-YYYY-##### numbering, create/apply/cancel
  endpoints, PDF template (`weasyprint`, same look as invoice PDF). When applied credit
  ≥ invoice.total → auto-transition invoice status=paid, payment_method=credit_note,
  reactivates services suspended for THAT invoice (mirrors Duitku webhook pattern with
  shared `_settle_invoice_from_credit` helper). Frontend `AdminCreditNotes.jsx` with
  create modal (+ auto_apply toggle) and status chips. `AdminInvoices` gets a `Refund`
  icon shortcut on unpaid/overdue rows. Client-visible read-only endpoint
  `GET /client/credit-notes` for their own credits.
- **NOC Monitor**: `run_noc_probe_sweep()` polls every MikroTik device every 5 min via the
  SAME `AsyncIOScheduler` (PRD constraint — no second scheduler). Writes `noc_probes`
  samples (24h uptime %), `noc_device_state` (current up/down), `noc_events` on real
  UP↔DOWN transitions only (no flap-storm). Alerts to `settings.noc_alert_recipients`
  (fallback to all role=admin users). New endpoints `GET /admin/noc/devices`,
  `GET /admin/noc/events`, `POST /admin/noc/run-poll`. Frontend `AdminNOC.jsx` with
  live KPI grid + device cards + transition event feed + auto-refresh (30s).
  Billing Defaults panel (AdminFinance) gets a `NOC alert recipients` textarea.
- **Menu registrations**: 3 new admin routes — `audit-log`/`noc`/`credit-notes` — with
  ADMIN_MENU_CATALOG entries (default_roles reflect finance/support/admin scope).
- **Tests**: `test_audit_credit_noc.py` (9 tests, all pass) covering audit filter shape,
  credit note partial→full settlement, exceeds-total rejection, cancel guard, PDF bytes,
  NOC idempotent poll.
- **Frontend testing agent iteration 31**: 7/8 review items pass; 1 HIGH regression noted
  in AdminMail (double-fetch inside open() caused stale-list race) — FIXED by using
  optimistic setSelected + patching row in-place instead of re-fetching inbox. Minor
  React <span-in-option> warning also cleaned up in AdminCreditNotes.

### Batch 6 — Duitku round-trip + Renewal automation + Reply + Installer hardening (2026-07-24)
- **DuitkuGateway per POP docs terkini** (`integrations_v2.py`): create signature
  HMAC_SHA256(merchantCode+timestamp, apiKey); callback verify HMAC_SHA256 primary +
  legacy MD5 fallback + merchantCode match; createInvoice mengirim returnUrl (wajib) +
  expiryPeriod, raise saat statusCode != 00. LIVE-verified di PRODUCTION (merchant D15021,
  env terdeteksi production — sandbox menolak "Merchant Not Found"). Kredensial di
  collection `integrations` (module duitku, enabled), TIDAK pernah hardcoded.
- **Webhook /webhooks/duitku idempotent**: transisi paid sekali saja (filter status!=paid);
  fire email `payment_received` (template baru + on_invoice_paid); auto-provision order;
  reaktivasi service suspended karena non-payment invoice tsb (set reactivated_at/reason).
  Duplicate callback → {duplicate:true} tanpa efek ganda; signature invalid → 400.
- **Duitku-only policy**: flag settings `enable_extra_payment_gateways` (default false)
  menyembunyikan midtrans/xendit dari /admin/integrations/modules, /admin/integrations,
  iv2 schema+list, dan memblokir pay-online/iv2-upsert. Class gateway TIDAK dihapus.
- **Renewal automation** (`emails.py`): run_renewal_invoice_sweep di scheduler yang sama
  (hourly :20 + startup). Guard duplikat: invoice.service_id+renewal_period; next_renewal
  maju satu siklus HANYA setelah insert sukses; nomor invoice max-based + retry duplikat.
  Settings: default_tax_percent, renewal_lead_days (GET/PUT /admin/billing/settings,
  manual trigger POST /admin/billing/run-renewal-sweep). PPN 11% hardcoded DIHAPUS dari
  order auto-invoice + preview (kini prefill dari settings, tetap manual per dokumen).
- **must_change_password chain**: install.sh generate password acak (openssl rand) bila
  ADMIN_PASSWORD tidak diberikan + tulis ADMIN_MUST_CHANGE_PASSWORD + REACT_APP_BACKEND_URL
  ke backend/.env; seed set flag; login/auth-me expose; change-password unset;
  PortalLogin redirect paksa ke settings/password.
- **Frontend**: AdminMail Reply button (prefill Re: + quoted body); ClientInvoices Pay with
  Duitku CTA nyata (pay-online → buka payment_url); AdminFinance tab "Billing Defaults".
- **Tests**: test_duitku_payment_flow.py (6), test_renewal_billing.py (6) — all pass;
  testing agent 39 sub-test green. Catatan: suite lama test_portal.py dkk gagal karena
  mengharapkan user staff demo yang tidak lagi di-seed (pre-existing, bukan regresi).
- Kredensial Duitku: merchant D15021 (production), API key tersimpan di DB integrations.
