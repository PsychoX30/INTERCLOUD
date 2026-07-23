# Intercloud Portal — Product Requirements

## Original Problem Statement
Continue developing an existing React + FastAPI + MongoDB customer/admin portal
imported from `intercloud-portal-source.zip`. Priorities included asset
depreciation (straight-line), Google reCAPTCHA v3, security dashboard, real
network diagnostics, full MikroTik integration with multi-device support, and
a whole-system optimisation pass (Performance / Security / SEO / UI-UX).

**User language:** Indonesian.

## Users
- **Admin** — full portal (finance, integrations, security, MikroTik ops, diagnostics).
- **Client (demo)** — services, invoices, tickets.

## Auth credentials
See `/app/memory/test_credentials.md`.

---

## Implemented (as of 2026-07-23)

### System Ops
- **Factory Reset** — `POST /api/portal/admin/system/factory-reset` (admin only).
  Wipes every non-preserved collection; preserves `settings` (branding + landing CMS)
  and all users where `role == admin`. Double-guarded (password re-entry + literal
  confirm phrase `FACTORY RESET`). Takes a `pre-factory-reset-*.archive.gz` safety
  snapshot before wiping. UI lives on Admin ▸ Backup, Restore & Update page (red
  DANGER ZONE card with per-collection deletion summary table on success).


### Finance & Assets
- Straight-Line Method (SLM) depreciation.

### Security integrations
- Google reCAPTCHA v3.
- Login Attempt Analytics dashboard with auto IP-blocking, whitelists, and
  Telegram bot notifications.

### Diagnostics (Admin ▸ Diagnostics)
- Real ping (`ping3`), traceroute (`/usr/sbin/traceroute` installed at runtime),
  DNS (`dig`), WHOIS, DNSBL blacklist, TCP port scan, HTTP HEAD, and Torch.

### MikroTik Ops (Admin ▸ MikroTik)
- Multi-device CRUD.
- Live ops on any device: Test connection, BGP peers, Looking Glass
  (ping/traceroute with **src-address**, bgp-route lookup via
  **longest-prefix scan**), Blackhole (list w/ **CIDR prefix filter**,
  add v7+v6 syntax, remove), Backup, Reboot, Traffic monitor.
- Token→plain login fallback, positional `librouteros` calls, `blackhole=yes`
  syntax for RouterOS 7, `?blackhole=yes` server-side filtering.

### System-wide optimisation (2026-07-23 — 4 phases)

**Phase 1 — Performance**
- All admin + client pages `React.lazy()` + `<Suspense>` (Landing kept eager
  for SEO/LCP). Initial bundle expected ~60-70% smaller.
- `GZipMiddleware` (minimum_size=1024) compresses JSON >1KB. **Middleware
  order matters**: GZip must be added FIRST (innermost, closest to app) so
  `GZipResponder` sees the raw response before BaseHTTPMiddleware-based
  wrappers (SlowAPI, SecurityHeaders) turn the body into a stream that
  hides Content-Length and breaks the minimum_size check.
- Compound MongoDB indexes on hot paths: `services.{user_id, status}`,
  `orders.{user_id, created_at}`, `invoices.{user_id, status}` +
  `{status, due_date}`, `tickets.{user_id, status}` + `{status, updated_at}`,
  `mikrotik_devices.{created_at, name}`, `articles.{published, published_at}`,
  `assets.{category, status}`, `email_queue.{status, scheduled_at}`.

**Phase 2 — Security**
- CORS whitelist read from `CORS_ORIGINS` env (production:
  `https://intercloud-digital.com` + `www.` subdomain +
  `https://intercloud-digital.preview.emergentagent.com`); wildcard `*` only
  when explicitly set (credentials disabled in that mode).
- `SecurityHeadersMiddleware` (portal/security.py): HSTS (1y +
  includeSubDomains + preload), X-Content-Type-Options=nosniff,
  X-Frame-Options=DENY, Referrer-Policy=strict-origin-when-cross-origin,
  Permissions-Policy (camera/mic/geo/payment blocked),
  `Content-Security-Policy-Report-Only` (per user preference).
- `/api/csp-report` receives violation reports and logs them.
- Rate limiting (slowapi with `headers_enabled=False` — the header injector
  is incompatible with BaseHTTPMiddleware-wrapped responses): `/auth/login`
  10/min, `/auth/register` 5/hour, `/auth/forgot-password` 5/hour,
  `/auth/reset-password` 10/hour. Returns HTTP 429 + `Retry-After: 60`.
- `SensitiveLogFilter` masks JWTs, bearer tokens, passwords, api-keys,
  and email addresses in log lines (partial-mask e-mail local-part).

**Phase 3 — SEO**
- `/robots.txt` (frontend/public/robots.txt) — allows public site,
  blocks `/portal` + `/api/portal`, points to sitemap on prod domain.
- `/api/portal/sitemap.xml` — dynamic, includes static routes
  (`/`, `/articles`, legal pages) + all published articles with `<lastmod>`.
  5-min public cache.
- Landing: canonical `<link>`, `BreadcrumbList` + `WebSite` (with
  `SearchAction`) JSON-LD.
- ArticleDetail: `BreadcrumbList` JSON-LD alongside the existing
  `BlogPosting` schema.

**Phase 4 — UI/UX polish**
- Global focus-visible ring (`outline: 2px solid #0a2540`), respects
  `prefers-reduced-motion`.
- Brand text-selection colour, iOS anti-flash body background.
- New reusable `<DataTable>` (sortable headers, filter, empty state,
  loading skeleton). Ready to roll out across Invoices/Orders/Services.
- New `<Skeleton />` / `<SkeletonText />` / `<SkeletonCard />` primitives.
- Improved lazy-route fallback (branded spinner instead of blank screen).

### Admin ▸ Branding (2026-07-23)
- Upload logo variants (`logo_light`, `logo_dark`), favicon, and email
  banner as base64 data-URIs stored in Mongo `settings.branding`. No
  filesystem writes, no re-deploy required.
- `GET  /api/portal/branding` — public (merges DB overrides on defaults).
- `POST /api/portal/admin/branding` — accepts any subset of the four keys;
  4 MB cap; unknown keys dropped.
- `DELETE /api/portal/admin/branding/{key}` — resets one field.
- Invoice / Quotation PDF renderers pass `logo_url=…` from the branding
  doc at request time; email `wrap_html(body, logo_url=…)` accepts the
  same override.
- Frontend page at `/portal/admin/branding` with drag-drop image upload,
  live preview against white/navy/slate backgrounds, per-field reset.
  Nav entry under `Admin ▸ System ▸ Branding`.

### Admin ▸ Landing CMS (2026-07-23)
- New Mongo doc `settings.landing_content` with three sections:
  `overrides` (i18n key → {id,en} map), `faqs` (list of Q/A pairs),
  `contact` (phone/email/address overrides — reserved for future).
- `GET  /api/portal/landing-content` — public (falls back to shipped
  defaults when empty).
- `POST /api/portal/admin/landing-content` — replaces the whole doc;
  128 KB cap; unknown top-level keys dropped.
- `DELETE /api/portal/admin/landing-content` — wipes all overrides.
- `LanguageProvider` fetches `/landing-content` at mount and merges
  `overrides` on top of the shipped translation dict. FAQ component
  reads `cmsFaqs` and falls back to `mock/data.js` if empty.
- Frontend page at `/portal/admin/site-content` with three tabs:
  **Text (curated)** — form editor for the 22 highest-value keys
  (hero, features, services, pricing, CTA, FAQ, footer);
  **FAQs** — add/remove bilingual Q/A pairs;
  **Raw JSON** — power-user full-document editor.

### Admin ▸ Backup / Restore (2026-07-23)
- `GET  /api/portal/admin/backup/download` — streams a
  `mongodump --archive --gzip` of every collection. Timestamped filename,
  no-store cache, downloadable via the browser.
- `POST /api/portal/admin/backup/restore?confirm=REPLACE` — raw request
  body is fed into `mongorestore --archive --gzip --drop`. Refuses to
  run without the `confirm=REPLACE` query string; refuses if body <32 B.
- Frontend page at `/portal/admin/backup` with Download button and a
  two-step Restore form: file picker + typed `REPLACE` confirmation +
  `window.confirm` prompt.

### First-boot seed reduced to admin-only (2026-07-23)
- `backend/portal/seed.py` now creates only the **admin** user. All demo
  data — sample client, sales/support/ticket_only staff users, sample
  products, invoices, tickets, articles — has been removed so a fresh
  install starts from a clean slate ready for real customers.
- Seeder remains idempotent: creates the admin on first boot; if
  `ADMIN_PASSWORD` in `backend/.env` later changes, the stored hash is
  re-synced so the operator can always log in.
- `install.sh` no longer emits `CLIENT_EMAIL` / `CLIENT_PASSWORD` in
  `backend/.env` — the seeder doesn't need them any more.
- `PortalLogin.jsx` no longer displays the "Demo credentials" block.
  Login screen shows only the standard form + "Create one" link.
- Existing installs are unaffected — no data is dropped by this change,
  it only prevents new demo rows from being *created* on subsequent
  boots. To wipe an existing DB, use Admin ▸ Backup, Restore & Update.
- `scripts/install.sh` — Ubuntu 24.04 LTS end-to-end installer:
  - OS deps + build tools (nginx, supervisor, python 3.12, node 20 + yarn,
    traceroute / dig / whois, jq, fail2ban, certbot, ufw)
  - **MongoDB 7.0** with `authorization: enabled`, per-install random
    password app user saved to `/etc/intercloud/mongo.env` (mode 600),
    `bindIp` locked to 127.0.0.1
  - System user `intercloud`, `git clone` into `/opt/intercloud-portal`
  - Python venv + backend deps
  - `backend/.env` with fresh Mongo URL, random 48-byte `JWT_SECRET`,
    CORS whitelist, and the seeder's expected env vars
    (`ADMIN_EMAIL` / `ADMIN_PASSWORD` / `CLIENT_EMAIL` / `CLIENT_PASSWORD`)
  - `frontend/.env` with `REACT_APP_BACKEND_URL`
  - `yarn install --frozen-lockfile && yarn build` → SPA served by nginx
  - nginx reverse proxy: `/api` → `127.0.0.1:8001`, SPA fallback,
    body 100 MB, read timeout 600 s, gzip on
  - supervisor program `intercloud-backend` (uvicorn, 2 workers)
  - **Daily backup cron** — `/etc/cron.d/intercloud-backup` triggers
    `scripts/daily-backup.sh` at 03:15 UTC into
    `/var/backups/intercloud/daily-YYYYMMDD.archive.gz`, atomic
    `.tmp→final` swap, 14-day rolling retention, log at
    `/var/log/intercloud-backup.log`
  - **fail2ban** jails — SSH default + custom `nginx-portal-auth`
  - **UFW firewall** (22 / 80 / 443)
  - **Let's Encrypt HTTPS via certbot** — triggered by `PORTAL_DOMAIN`
    + `LETSENCRYPT_EMAIL`; `certbot.timer` enabled for auto-renewal
  - **Admin seed verification** — round-trips a real login before exit
  - Idempotent — safe to re-run
- `scripts/update.sh` — auto-snapshots DB (atomic `.tmp` swap) into the
  same `/var/backups/intercloud/` directory as `pre-update-*.archive.gz`
  (30-day retention), refuses on dirty tree, refuses if no git remote,
  `git pull --ff-only`, reinstalls deps, rebuilds frontend, restarts
  backend.
- `scripts/daily-backup.sh` — standalone script also usable ad-hoc:
  `sudo APP_DIR=/opt/intercloud-portal bash scripts/daily-backup.sh`
- `POST /api/portal/admin/system/update?confirm=UPDATE` — file-locked via
  `flock(/tmp/intercloud-update.lock)` so concurrent clicks return 409.
- Full deployment guide at `/app/docs/production.md`.

---

## Verified endpoints (2026-07-23)
- `POST /api/portal/admin/mikrotik/devices/{id}/test`
- `POST /api/portal/admin/mikrotik/looking-glass` (accepts optional `src_address`, `match_prefix` in response)
- `GET  /api/portal/admin/mikrotik/blackhole?device_id&prefix_filter`
- `POST /api/portal/admin/diagnostics/run`
- `GET  /api/portal/sitemap.xml`
- `POST /api/portal/admin/system/factory-reset` (admin_password + confirm="FACTORY RESET")

## Live-verified against real hardware
- RouterOS 7.20.6 — `TO.DIST` (157.20.32.253:8777) and `RO.BGP`
  (157.20.32.254:8777).

## Regression suites
- `/app/backend/tests/test_mikrotik_signature.py` (11)
- `/app/backend/tests/test_looking_glass.py` (7)
- `/app/backend/tests/test_mikrotik_blackhole_live.py` (12)
- `/app/backend/tests/test_looking_glass_live.py` (11)

---

## Backlog

**P1 — Roll out `<DataTable>`** across Invoices, Orders, Services, Users,
Assets. Wrap each screen's table with the new component + provide
`columns`/`searchKeys` — 30-min-per-screen job.

**P2 — Environment**
- Bake `traceroute` (+ `dig`, `whois`) into the backend container image
  (currently apt-installed at runtime, not persisted).
- Bump Referrer-Policy to `no-referrer` once analytics tags are ready.

**P2 — Optimisations**
- Parallelise `_bgp_route_lookup` prefix scan via asyncio for sub-2s
  BGP lookups on full-BGP routers.
- Server-side traffic history collection (persist rx/tx samples to Mongo).
- After 2-4 weeks of `CSP-Report-Only` clean logs, promote CSP to
  `Content-Security-Policy` (enforce mode).

**P2 — Auth**
- Zod + `react-hook-form` inline validation on Login / Register /
  ForgotPassword forms (dependencies already installed).

---

## Architecture
```
/app/backend/portal/
├── integrations_v2.py     # Proxmox, MikrotikClient, payments, Recaptcha, Telegram
├── diagnostics.py         # ping/traceroute/dns/whois/blacklist/portscan/http/torch
├── routes.py              # FastAPI endpoints (all under /api/portal)
├── security.py            # limiter + SecurityHeadersMiddleware + LogFilter
└── seed.py

/app/frontend/src/
├── App.js                 # React.lazy() split + Suspense fallback
├── components/ui/
│   ├── data-table.jsx     # NEW reusable table
│   └── skeleton.jsx       # NEW skeleton primitives
├── pages/
│   ├── Landing.jsx        # canonical + BreadcrumbList + WebSite JSON-LD
│   ├── ArticleDetail.jsx  # BlogPosting + BreadcrumbList JSON-LD
│   └── portal/…
├── public/
│   └── robots.txt         # NEW
└── index.css              # focus-visible, reduced-motion, brand selection
```
