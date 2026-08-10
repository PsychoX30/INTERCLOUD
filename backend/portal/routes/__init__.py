"""Portal API routes package (modular split of the former routes.py)."""
from fastapi import APIRouter

from . import (auth, client, orders, tickets, admin_core, users, catalog,
               billing, finance, lifecycle, integrations, business, dcim,
               provision, cms, documents, domains, ssl, noc, security, email_admin,
               transactions, sla)
from .shared import _ip_in_whitelist  # noqa: F401 (test compat)

router = APIRouter(prefix="/api/portal")
router.include_router(auth.router)
router.include_router(client.router)
router.include_router(orders.router)
router.include_router(tickets.router)
router.include_router(admin_core.router)
router.include_router(users.router)
router.include_router(catalog.router)
router.include_router(billing.router)
router.include_router(finance.router)
router.include_router(lifecycle.router)
router.include_router(integrations.router)
router.include_router(business.router)
router.include_router(dcim.router)
router.include_router(provision.router)
router.include_router(cms.router)
router.include_router(documents.router)
router.include_router(domains.router)
router.include_router(ssl.router)
router.include_router(noc.router)
router.include_router(security.router)
router.include_router(email_admin.router)
router.include_router(transactions.router)
router.include_router(sla.router)
