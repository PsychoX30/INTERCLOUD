# RBAC Matrix & Feature/Menu Update Rules

> Scope: feature gap audit implementation (Transaction Ledger, KB Authoring, SLA Internal + PDF, RBAC scoping fixes).
> Date: 2026-08-10
> Repo: /home/support/INTERCLOUD
> Base commit: 530496a

## 1. Role Definitions

| Role | Purpose |
|------|---------|
| `admin` | Full access; configuration; destructive operations; finance; support; creative. |
| `owner` | Executive overview only (dashboard). |
| `finance` | All finance/accounting data; all invoices; assets; expenses; credit notes; bank accounts; transactions. |
| `sales` | Assigned-client view only: CRM, follow-ups, tickets, orders, quotations, transactions, SLA incidents that affect assigned clients. |
| `support` | Operations + support: tickets, devices, NOC, DCIM, diagnostics, products, services, KB authoring. No finance, no billing settings, no client invoices. |
| `ticket_only` | Tickets only (no CRM/finance/orders). |
| `client` | Self-service portal only. |
| `creative` | Articles/media/CMS tools only. Denied from billing/CRM/NOC/finance. |

## 2. Backend Enforcement Matrix

| Module | Endpoint(s) | Allowed Roles | Sales Scope |
|--------|-------------|---------------|-------------|
| Invoices | `/admin/invoices`, `/{id}`, `/{id}/email`, `/{id}/pdf` | admin, finance | `_sales_scope_filter(user_id)` on GET/detail/email/PDF |
| Quotations | `/admin/quotations`, `/{id}`, `/documents/quotation/{qid}` | admin, sales, finance | `_sales_scope_filter(user_id)` on PDF render |
| Orders | `/admin/orders/{id}` (update) | get_current_staff | `_sales_scope_filter(user_id)` |
| Tickets | `/admin/tickets/*` (list, detail, reply, timeline, device) | admin, sales, finance, support, ticket_only | `_sales_scope_filter(user_id)` |
| CRM | `/admin/crm` | admin, sales, finance, support | `_sales_scope_filter(user_id)` |
| Follow-ups | `/admin/followups` | admin, sales, finance, support | `_sales_scope_filter(user_id)` |
| Transactions | `/admin/transactions`, `/summary`, `/{id}` | admin, finance, sales | `_sales_scope_filter(user_id)` |
| SLA Incidents | `/admin/sla/incidents`, `/{id}`, `/report/pdf` | admin, support, finance, sales | `_sales_scope_filter_for_incidents(affected_customers)` |
| SLA Config | `/admin/sla/config` | admin only | N/A |
| Finance module | `/admin/finance/*`, `/admin/assets`, `/admin/expenses`, `/admin/credit-notes`, `/admin/bank-accounts` | admin, finance | N/A |
| Billing settings | `/admin/billing/settings` | admin, finance | N/A |
| KB Articles | `/admin/articles` | admin, sales, finance, support, creative | Support can only create/edit `type=kb`; delete blocked for support |
| Public KB | `/public/articles?type=kb` | public | N/A |

## 3. Frontend Menu Visibility

Menu items are rendered by `frontend/src/pages/portal/PortalLayout.jsx` using per-item `roles` arrays. Roles must match `ADMIN_MENU_CATALOG` in `backend/portal/routes/users.py`.

| Menu Key | Visible To |
|----------|-----------|
| `transactions` | admin, finance, sales |
| `sla` | admin, support, finance, sales |
| `articles` | admin, sales, finance, support, creative |
| `invoices` | admin, finance |
| `finance` | admin, finance |
| `assets` | admin, finance |
| `credit_notes` | admin, finance |
| `noc` | admin, support |
| `dcim` | admin, support |
| `mikrotik` | admin, support |
| `domains` | admin, support |
| `ssl` | admin, support |

## 4. Rule: Adding a New Admin Menu / Feature

When adding a new admin page or API module, update **all four** of these consistently:

1. **Backend route** — apply `require_roles(...)` or `get_current_staff` + explicit role checks.
2. **Sales/client scope** — if the resource belongs to a user, apply `_sales_scope_filter(staff, key="user_id")` (or a custom scoping helper for non-user resources, e.g. `_sales_scope_filter_for_incidents`).
3. **Frontend menu** — add entry to `ADMIN_MENU` in `frontend/src/pages/portal/PortalLayout.jsx` with the correct `roles` array.
4. **Backend catalog** — add entry to `ADMIN_MENU_CATALOG` in `backend/portal/routes/users.py` with matching `default_roles`.
5. **Feature flag** — if the feature is destructive, cross-role, or opt-in, add a `FEATURE_FLAG_CATALOG` entry and enforce it in the route (frontend currently only hides UI; backend is the source of truth).

## 5. Anti-Patterns to Avoid

- Do **not** rely on frontend hiding alone; backend must reject unauthorized requests.
- Do **not** let `sales` see all records of a module; always scope to `assigned_client_ids`.
- Do **not** let `support` mutate global billing/finance settings.
- Do **not** let `creative` access CRM, billing, NOC, or finance data.
- Do **not** define a route path after a dynamic `/{id}` route that could be swallowed (e.g. `/summary` must be declared before `/{tid}`).

## 6. Verification Commands

```bash
cd /home/support/INTERCLOUD/backend
/tmp/intercloud-venv/bin/python -m pytest tests/test_sla_contract.py tests/test_transaction_ledger_contract.py tests/test_kb_authoring_contract.py -q

python3 -m py_compile portal/models.py portal/routes/__init__.py portal/routes/sla.py portal/routes/billing.py portal/routes/shared.py portal/routes/transactions.py portal/routes/tickets.py portal/routes/orders.py portal/routes/documents.py portal/routes/finance.py portal/routes/cms.py portal/routes/users.py portal/auth.py

cd /home/support/INTERCLOUD/frontend
npm run build
```

## 7. Known Out-of-Scope Gaps

- `can_manage_articles` feature flag is declared but **not enforced** in the backend. Support role is the practical KB-author gate today.
- `menu_keys` / `feature_flags` overrides are stored per-user but backend only reads role; frontend reads the override.
- Frontend route guards beyond `RequireAuth` are minimal; backend is the enforcement layer.
