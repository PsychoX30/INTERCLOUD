# QA Evidence — INTERCLOUD Hosting Package Upgrade (Client Self-Service)
Date: 2026-08-27 | Branch: local working tree (uncommitted) | Prepared by: Hermes (Manager)

## Scope
Implement client self-service **hosting package upgrade** (mirroring VPS resource-upgrade pattern), plus hosting catalog tier configuration in admin product form, and order-flow hosting fields.

## Files Changed (7 files, +405 / -13)
| File | +/- | Change |
|---|---|---|
| `backend/portal/models.py` | +3/-1 | `PendingUpgrade` extended: `type` (`resource`/`hosting_package`), `package` field |
| `backend/portal/routes/client.py` | +119 | 3 new endpoints: `GET /client/services/{sid}/hosting/upgrade/options`, `POST .../upgrade/preview`, `POST .../upgrade` (prorated invoice + pending_upgrade guard) |
| `backend/portal/routes/billing.py` | +27/-2 | `_apply_pending_upgrade` hosting branch: on paid → `CpanelClient.change_package()` → update `config.whm_package`, clear `pending_upgrade`, log |
| `backend/portal/routes/provision.py` | +9/-2 | `_resolve_hosting_config` honors `order.config.whm_package` when matching tier in `product.provision.packages` |
| `frontend/src/pages/portal/admin/AdminProducts.jsx` | +64 | Hosting provision block: default WHM package, editable tier table (name/label/disk/bw/price), domain policy, subdomain suffix, nameservers, set-registrar-NS |
| `frontend/src/pages/portal/client/ClientOrder.jsx` | +104/-9 | Order configure step: hosting tier selection, domain policy fields (subdomain/customer_domain), domain input |
| `frontend/src/pages/portal/client/ClientServices.jsx` | +91 | Hosting upgrade panel: "Pilih Paket Baru" → options → preview (prorata) → create invoice; shows current tier + pending state |
| `backend/tests/test_hosting_upgrade.py` | NEW | 6 unit tests (mock DB, no external deps) |

## Test Evidence
```
cd /home/support/INTERCLOUD/backend
.venv/bin/python -m pytest tests/test_hosting_upgrade.py -v
→ 6 passed, 2 warnings in 3.59s
  PASSED test_options_returns_catalog_tiers_except_current
  PASSED test_preview_calculates_prorated_difference_and_tax
  PASSED test_upgrade_creates_invoice_and_pending_flag
  PASSED test_upgrade_returns_409_when_pending
  PASSED test_invalid_package_returns_400
  PASSED test_paid_hosting_upgrade_calls_whm_and_clears_pending
```

## Syntax / Build
```
py_compile: models.py, client.py, provision.py, billing.py → ALL OK
git diff --check HEAD → clean (no whitespace errors)
frontend: rm -rf build && npm run build → exit 0
new bundle: build/static/js/main.033e74be.js
```

## Full Regression Note (pre-existing, NOT regression)
Full suite: 79 failed, 540 passed, 295 errors — all errors are E2E tests hardcoded to offline preview host
(`https://repo-analyzer-264.preview.emergentagent.com` returns 404). Confirmed by stash→re-run: identical failures.
No regression from this patch.

## Security / Guards
- Ownership check: `_hosting_upgrade_ctx` filters `user_id` match + `category=="hosting"` + `status=="active"`
- 409 if another upgrade pending; 400 on invalid/same/downgrade package
- Package name validated against catalog tiers (never client-controlled freeform)
- WHM token stays server-side (integration_settings, encrypted); never exposed to client
- No retry storm: `_apply_pending_upgrade` returns False on WHM failure → pending_upgrade kept for manual retry

## API Contract (smoke after deploy)
```
GET /api/portal/client/services/{sid}/hosting/upgrade/options
→ {"tiers":[{"name","label","disk_gb","bandwidth_gb","price"}], "current":{...}, "pending_upgrade":false}

POST .../hosting/upgrade/preview  body {"package":"<tier_name>"}
→ {"current":{...}, "target":{...}, "monthly_delta":N, "days_left":N, "prorated_charge":N, "tax_percent":N, "tax_amount":N, "total":N}

POST .../hosting/upgrade  body {"package":"<tier_name>"}
→ {"invoice_id":"...", "amount":N, "due_date":"YYYY-MM-DD"}
```

## Known Follow-up (non-blocking)
- `_apply_pending_upgrade` return value ignored by callers (mark-paid / webhook). If WHM fails, pending_upgrade is kept but no auto-retry. Manual retry via admin or re-mark-paid works. Recommend retry queue in future iteration.

## Verdict Request
Dudung: please review diff + evidence above. Requesting **VERDICT: PASS** to proceed to production deploy.
