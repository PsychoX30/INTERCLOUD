"""Regression tests for the new Pusat Notifikasi alerts.

Covers the alert types added to ``_build_admin_alerts``:
- ``followup_overdue``      (follow-up jatuh tempo / lewat tempo)
- ``crm_assignment_expiry`` (assignment prospect segera lepas)
- ``service_renewal``       (layanan segera perpanjangan)

Focus of these tests is role scoping: a sales user must only ever see their
own follow-ups / their own assigned prospects, and renewal alerts are a
finance-scoped concern.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

from portal.routes import admin_core


TODAY = datetime.now(timezone.utc).date()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()


class _Cursor:
    """Minimal async cursor: records the query, replays canned docs."""

    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, *_a, **_kw):
        return self

    def skip(self, *_a):
        return self

    def limit(self, *_a):
        return self

    async def to_list(self, _n=None):
        return list(self._docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class _Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.queries = []

    def find(self, query=None, *_a, **_kw):
        self.queries.append(query or {})
        return _Cursor(self.docs)

    async def count_documents(self, query=None):
        self.queries.append(query or {})
        return len(self.docs)


class _DB:
    """Fake Mongo handle; unknown collections resolve to empty ones."""

    def __init__(self, **collections):
        self._cols = {}
        for name, docs in collections.items():
            self._cols[name] = _Collection(docs)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._cols.setdefault(name, _Collection())


SALES_ID = ObjectId()
SALES = {"id": str(SALES_ID), "role": "sales", "assigned_client_ids": []}
ADMIN = {"id": str(ObjectId()), "role": "admin"}
FINANCE = {"id": str(ObjectId()), "role": "finance"}
CREATIVE = {"id": str(ObjectId()), "role": "creative"}
TICKET_ONLY = {"id": str(ObjectId()), "role": "ticket_only"}


def _types(alerts):
    return [a["type"] for a in alerts]


@pytest.mark.anyio
async def test_overdue_followup_emits_warning_alert():
    db = _DB(followups=[{"_id": ObjectId(), "customer_name": "PT Contoh",
                         "task": "Telepon ulang", "due_date": YESTERDAY,
                         "done": False, "owner_id": str(SALES_ID)}])

    alerts = await admin_core._build_admin_alerts(db, ADMIN)

    fu = [a for a in alerts if a["type"] == "followup_overdue"]
    assert len(fu) == 1
    assert fu[0]["severity"] == "warning"
    assert "PT Contoh" in fu[0]["title"]
    assert fu[0]["link"] == "/portal/admin/crm"


@pytest.mark.anyio
async def test_sales_followup_query_is_scoped_to_own_owner_id():
    db = _DB(followups=[])

    await admin_core._build_admin_alerts(db, SALES, [])

    q = [q for q in db.followups.queries if "done" in q][0]
    assert q["owner_id"] == str(SALES_ID)


@pytest.mark.anyio
async def test_admin_followup_query_is_not_owner_scoped():
    db = _DB(followups=[])

    await admin_core._build_admin_alerts(db, ADMIN)

    q = [q for q in db.followups.queries if "done" in q][0]
    assert "owner_id" not in q


@pytest.mark.anyio
async def test_creative_and_ticket_only_get_no_followup_or_crm_alerts():
    for staff in (CREATIVE, TICKET_ONLY):
        db = _DB(
            followups=[{"_id": ObjectId(), "customer_name": "X",
                        "due_date": YESTERDAY, "done": False}],
            crm_customers=[{"_id": ObjectId(), "name": "Lead",
                            "status": "assigned",
                            "assignment_expires_at": TOMORROW}],
        )

        alerts = await admin_core._build_admin_alerts(db, staff)

        assert "followup_overdue" not in _types(alerts)
        assert "crm_assignment_expiry" not in _types(alerts)


@pytest.mark.anyio
async def test_expiring_crm_assignment_emits_alert_for_admin():
    db = _DB(crm_customers=[{"_id": ObjectId(), "name": "Lead Panas",
                             "status": "assigned",
                             "assignment_expires_at": TOMORROW}])

    alerts = await admin_core._build_admin_alerts(db, ADMIN)

    crm = [a for a in alerts if a["type"] == "crm_assignment_expiry"]
    assert len(crm) == 1
    assert crm[0]["severity"] == "warning"
    assert "Lead Panas" in crm[0]["title"]


@pytest.mark.anyio
async def test_sales_crm_assignment_query_scoped_to_own_object_id():
    db = _DB(crm_customers=[])

    await admin_core._build_admin_alerts(db, SALES, [])

    q = [q for q in db.crm_customers.queries if q.get("status") == "assigned"][0]
    assert q["assigned_to"] == SALES_ID


@pytest.mark.anyio
async def test_finance_sees_service_renewal_alert():
    db = _DB(services=[{"_id": ObjectId(), "product_name": "Hosting Bisnis",
                        "status": "active", "next_renewal": TOMORROW}])

    alerts = await admin_core._build_admin_alerts(db, FINANCE)

    ren = [a for a in alerts if a["type"] == "service_renewal"]
    assert len(ren) == 1
    assert ren[0]["severity"] == "info"
    assert "Hosting Bisnis" in ren[0]["title"]
    assert ren[0]["link"] == "/portal/admin/services"


@pytest.mark.anyio
async def test_sales_does_not_get_service_renewal_alert():
    db = _DB(services=[{"_id": ObjectId(), "product_name": "Hosting Bisnis",
                        "status": "active", "next_renewal": TOMORROW}])

    alerts = await admin_core._build_admin_alerts(db, SALES, [])

    assert "service_renewal" not in _types(alerts)


@pytest.mark.anyio
async def test_alerts_remain_sorted_by_severity():
    db = _DB(
        followups=[{"_id": ObjectId(), "customer_name": "Lewat",
                    "due_date": YESTERDAY, "done": False}],
        services=[{"_id": ObjectId(), "product_name": "Renew",
                   "status": "active", "next_renewal": TOMORROW}],
    )

    alerts = await admin_core._build_admin_alerts(db, ADMIN)

    rank = {"danger": 0, "warning": 1, "info": 2}
    seq = [rank[a["severity"]] for a in alerts]
    assert seq == sorted(seq)
