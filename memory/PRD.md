# Intercloud Portal — Product Requirements

## Original Problem Statement
Continue developing an existing React + FastAPI + MongoDB customer/admin portal
imported from `intercloud-portal-source.zip`. Priorities included asset
depreciation (straight-line), Google reCAPTCHA v3, security dashboard, real
network diagnostics, and full MikroTik integration with multi-device support.

**User language:** Indonesian.

## Users
- **Admin** — full portal (finance, integrations, security, MikroTik ops, diagnostics).
- **Client (demo)** — services, invoices, tickets.

## Auth credentials
See `/app/memory/test_credentials.md`.

---

## Implemented (as of 2026-07-23)

### Finance & Assets
- Straight-Line Method (SLM) depreciation in `routes.py`, exposed in
  `AdminAssets.jsx` & `AdminFinance.jsx`.

### Security
- Google reCAPTCHA v3 (backend `RecaptchaV3Verifier`, frontend `recaptcha.js`,
  wired into Login / Register / Forgot Password).
- Login Attempt Analytics dashboard with auto IP-blocking, whitelists, and
  Telegram bot notifications (`TelegramNotifier`).

### Diagnostics (Admin ▸ Diagnostics)
- Real ping (`ping3`), traceroute (`/usr/sbin/traceroute` installed), DNS
  (`dig`), WHOIS, DNSBL blacklist, TCP port scan, HTTP HEAD, and Torch (via
  MikroTik `/tool/torch`).

### MikroTik Looking Glass
- Ping and Traceroute now accept an optional **src-address** — forwarded to
  RouterOS so ops can probe from a specific interface / loopback.
- BGP Route Lookup now uses **longest-prefix scan via server-side query**
  (`rawCmd('/ip/route/print', '?dst-address=IP/LEN')` from /32 down to /0),
  replacing the previous `startswith` filter that never matched a covering
  prefix (e.g. `103.133.20.0/24` for the IP `103.133.20.5`). Response
  populates `match_prefix` so the UI can show the covering route.

### MikroTik Ops (Admin ▸ MikroTik)
- Multi-device CRUD (`mikrotik_devices` collection) — each device has
  host, port, username, password, use_tls, site.
- Live ops on any device: Test connection, BGP peers, Looking Glass
  (ping/traceroute/bgp-route from the router), Blackhole
  (list/add/remove **with optional CIDR prefix filter**), Backup
  (list/create/delete), Reboot with double-confirm, Traffic monitor
  (rx/tx bps, live line chart w/ 30-sample rolling window).
- **Login fallback**: `MikrotikClient._connect` tries `token` login first
  then falls back to `plain` on any auth failure, so pre-6.43 RouterOS and
  plain-only accounts both work without extra config.
- **Correct librouteros call**: uses positional `api("/path", ...)`. The
  previous `api(cmd="/path", ...)` crashed at runtime because
  `Api.__call__(self, cmd: str, /, **kwargs)` is positional-only.
- **RouterOS 7 blackhole syntax** (fix, 2026-07-23): `/ip/route/add` uses
  `blackhole=yes` (v7); the previous `type=blackhole` (v6) raised
  `TrapError: unknown parameter type`. `blackhole_add` now tries v7 first
  then falls back to v6, so both worlds work.
- **Fast blackhole list on full-BGP routers** (fix, 2026-07-23):
  `blackhole_list` uses `api.rawCmd("/ip/route/print", "?blackhole=yes")`
  so RouterOS filters server-side. Response time on TO.DIST (full BGP
  table, ~900k prefixes) dropped from timeout to <2s. Optional
  `prefix_filter` (CIDR) narrows further client-side via
  `ipaddress.subnet_of`.
- Regression-guarded by `/app/backend/tests/test_mikrotik_signature.py`
  (11 tests, wire-level fake `ApiProtocol`) and
  `/app/backend/tests/test_mikrotik_blackhole_live.py`
  (12 tests, real RouterOS 7.20.6).

### Diagnostics dependencies
- Container packages: `traceroute` (installed via apt, `/usr/sbin/traceroute`),
  `dig`, `whois`. Python: `ping3`, `librouteros==4.1.1`.

---

## Live endpoints of note
- `POST /api/portal/admin/mikrotik/devices/{id}/test` — verifies against real router
- `POST /api/portal/admin/mikrotik/looking-glass` — ping/traceroute/bgp_route
- `GET  /api/portal/admin/mikrotik/traffic?device_id&interface` — one-shot monitor
- `GET  /api/portal/admin/mikrotik/interfaces?device_id`
- `POST /api/portal/admin/integrations-v2/mikrotik/test` — legacy single-device test
- `POST /api/portal/admin/diagnostics/run` — dispatcher for all diagnostic tools

## Verified on live devices (2026-07-23)
- RouterOS 7.20.6 stable — `TO.DIST` (157.20.32.253:8777) and
  `RO.BGP` (157.20.32.254:8777) — token login accepted.
- All ops return real data (ping RTT, traceroute hops, backups list, traffic
  counters, interfaces list of 20 items).

---

## P1 — Upcoming
- **Phase 4 Performance**: lazy-load routes, memoize heavy tables, add MongoDB
  indexes for `login_attempts.timestamp`, `invoices.status`, `services.status`.
- **Phase 5 UI/UX polish**: unified design tokens, inline form validation,
  sortable/filterable tables with proper empty-states.

## P2 — Backlog
- **Phase 6 QA & Handover**: smoke test across all modules.
- Persist traceroute install in a Dockerfile / setup script (currently
  installed at runtime via `apt-get install -y traceroute`).
- Consider a persistent traffic history collection (currently only 30 in-memory
  samples in the browser).

---

## Architecture
```
/app/backend/portal/
├── integrations_v2.py   # Proxmox, MikrotikClient, payment gateways, Recaptcha, Telegram
├── diagnostics.py       # ping/traceroute/dns/whois/blacklist/portscan/http/torch
├── routes.py            # FastAPI endpoints (all /api-prefixed via ingress)
└── seed.py

/app/frontend/src/pages/portal/admin/
├── AdminMikrotik.jsx    # Devices, BGP, Looking Glass, Blackhole, Backup, Restart, Traffic
├── AdminDiagnostics.jsx
├── AdminSecurity.jsx
└── AdminAssets.jsx

/app/backend/tests/
└── test_mikrotik_signature.py   # 9 pytest cases guarding librouteros signature
```
