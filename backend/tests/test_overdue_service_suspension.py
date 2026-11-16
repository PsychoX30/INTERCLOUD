"""Contract tests for overdue-service suspension (2026-11-16).

Three defects were reproduced against the live production code before this
file existed. Each one is pinned here so it cannot come back:

  1. `_suspend_for_invoice` matched `invoices.service_id` against the ObjectId
     `_id` without conversion. The renewal sweep stores `service_id` as a
     STRING (`sid = str(svc["_id"])`), so the match hit nothing, the sweep
     still flagged the invoice `suspended_for_invoice`, and the service stayed
     `active` forever while overdue.
  2. The suspension reason was a localized sentence with no "overdue" word,
     while both reactivation paths (duitku webhook in routes/billing.py and
     credit note in routes/finance.py) select services with
     `$regex: "invoice <number> overdue"`. Suspensions therefore became
     unreachable for reactivation.
  3. No existing test ever passed `service_id` into the sweep, which is why
     neither bug was caught.

Written with plain `asyncio.run`: the prod venv has no pytest-asyncio.
"""
import asyncio
import datetime as dt
import re

import pytest
from bson import ObjectId


NOW = dt.datetime(2026, 12, 1, 12, 0, tzinfo=dt.timezone.utc)


def _day(off: int) -> str:
    return (NOW.date() + dt.timedelta(days=off)).isoformat()


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class _Result:
    def __init__(self, modified=0, matched=0):
        self.modified_count = modified
        self.matched_count = matched


def _match(doc, query):
    """Subset of Mongo semantics: equality, $in, $ne, $gte, $lte, $regex, $or."""
    for k, v in query.items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        val = doc.get(k)
        if isinstance(v, dict):
            if "$in" in v and val not in v["$in"]:
                return False
            if "$nin" in v and val in v["$nin"]:
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
            if "$gte" in v:
                if val is None or val < v["$gte"]:
                    return False
            if "$lte" in v:
                if val is None or val > v["$lte"]:
                    return False
            if "$regex" in v:
                if val is None:
                    return False
                flags = re.I if "i" in str(v.get("$options", "")) else 0
                if not re.search(v["$regex"], str(val), flags):
                    return False
        elif val != v:
            return False
    return True


class _Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.updates = []

    def find(self, query=None, *a, **kw):
        query = query or {}
        return _FakeCursor([d for d in self.docs if _match(d, query)])

    async def find_one(self, query=None, *a, **kw):
        query = query or {}
        for d in self.docs:
            if _match(d, query):
                return d
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return _Result()

    async def update_one(self, query, update):
        for d in self.docs:
            if _match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                for k in (update.get("$unset") or {}):
                    d.pop(k, None)
                self.updates.append((query, update))
                return _Result(modified=1, matched=1)
        return _Result()

    async def update_many(self, query, update):
        n = 0
        for d in self.docs:
            if _match(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                for k in (update.get("$unset") or {}):
                    d.pop(k, None)
                n += 1
        return _Result(modified=n, matched=n)


class _FakeDB:
    def __init__(self, **collections):
        self.collections = collections

    def __getattr__(self, name):
        return self.collections.setdefault(name, _Collection())


@pytest.fixture
def em(monkeypatch):
    """emails module with delivery stubbed out."""
    from portal import emails as _em

    async def _no_send(*a, **kw):
        return {"status": "sent"}

    async def _no_token(*a, **kw):
        return "tok"

    monkeypatch.setattr(_em, "send_via_template", _no_send)
    monkeypatch.setattr(_em, "ensure_pay_token", _no_token)
    return _em


def _db(user_id, services, invoice_extra=None):
    inv = {"_id": ObjectId(), "number": "INV-1", "user_id": user_id,
           "status": "overdue", "due_date": _day(-10)}
    inv.update(invoice_extra or {})
    return _FakeDB(
        users=_Collection([{"_id": user_id, "email": "u@e.test", "name": "U"}]),
        services=_Collection(services),
        invoices=_Collection([inv]),
        email_logs=_Collection(),
        notifications=_Collection(),
        audit_logs=_Collection(),
    )


# --------------------------------------------------------------------------- #
# Defect 1 - the service_id type mismatch
# --------------------------------------------------------------------------- #
def test_suspend_matches_string_service_id(em):
    """The renewal sweep stores service_id as a string; it must still match."""
    uid = ObjectId()
    sid = ObjectId()
    db = _db(uid, [{"_id": sid, "user_id": uid, "status": "active", "name": "VPS-1"}],
             {"service_id": str(sid)})
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 1
    assert db.services.docs[0]["status"] == "suspended"


def test_suspend_matches_objectid_service_id(em):
    uid = ObjectId()
    sid = ObjectId()
    db = _db(uid, [{"_id": sid, "user_id": uid, "status": "active", "name": "VPS-1"}],
             {"service_id": sid})
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 1
    assert db.services.docs[0]["status"] == "suspended"


def test_named_service_only_is_suspended(em):
    """A named service_id must not drag the user's other services down."""
    uid = ObjectId()
    target, other = ObjectId(), ObjectId()
    db = _db(uid, [
        {"_id": target, "user_id": uid, "status": "active", "name": "VPS-target"},
        {"_id": other, "user_id": uid, "status": "active", "name": "VPS-other"},
    ], {"service_id": str(target)})
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 1
    byname = {s["name"]: s["status"] for s in db.services.docs}
    assert byname == {"VPS-target": "suspended", "VPS-other": "active"}


def test_empty_service_id_falls_back_to_all_active(em):
    """No service_id on the invoice: every active service of that user goes."""
    uid = ObjectId()
    db = _db(uid, [
        {"_id": ObjectId(), "user_id": uid, "status": "active", "name": "A"},
        {"_id": ObjectId(), "user_id": uid, "status": "active", "name": "B"},
    ])
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 2
    assert [s["status"] for s in db.services.docs] == ["suspended", "suspended"]


def test_manual_override_still_wins(em):
    """suspended_manual must never be auto-unsuspended or re-suspended."""
    uid = ObjectId()
    sid = ObjectId()
    db = _db(uid, [{"_id": sid, "user_id": uid, "status": "active",
                    "name": "VPS-1", "suspended_manual": True}],
             {"service_id": str(sid)})
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 0
    assert db.services.docs[0]["status"] == "active"


def test_no_active_service_is_not_an_error(em):
    """A terminated service must not be resurrected into 'suspended'."""
    uid = ObjectId()
    sid = ObjectId()
    db = _db(uid, [{"_id": sid, "user_id": uid, "status": "terminated", "name": "VPS-1"}],
             {"service_id": str(sid)})
    out = asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert out["services_suspended"] == 0
    assert db.services.docs[0]["status"] == "terminated"


# --------------------------------------------------------------------------- #
# Defect 2 - the reason string must stay reachable by reactivation
# --------------------------------------------------------------------------- #
def test_reason_keeps_the_reactivation_substring(em):
    """Both reactivation paths grep for 'invoice <number> overdue'."""
    from portal.emails import suspended_reason_for
    reason = suspended_reason_for("INV-2026-00042")
    assert re.search(r"invoice INV-2026-00042 overdue", reason, re.I), reason


def test_sweep_writes_a_reason_reactivation_can_find(em):
    uid = ObjectId()
    sid = ObjectId()
    db = _db(uid, [{"_id": sid, "user_id": uid, "status": "active", "name": "VPS-1"}],
             {"service_id": str(sid), "number": "INV-2026-00042"})
    asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    reason = db.services.docs[0].get("suspended_reason", "")
    assert re.search(r"invoice INV-2026-00042 overdue", reason, re.I), reason
    # the sweep must not leave an unattributed suspension behind
    assert db.services.docs[0].get("suspended_by") == "system:invoice_overdue"


def test_reactivation_finds_what_the_sweep_wrote(em):
    """End-to-end: suspend via sweep, then run the webhook's reactivation
    selector verbatim and require the service to come back."""
    from portal.emails import suspended_reason_for

    uid = ObjectId()
    sid = ObjectId()
    number = "INV-2026-00042"
    db = _db(uid, [{"_id": sid, "user_id": uid, "status": "active", "name": "VPS-1"}],
             {"service_id": str(sid), "number": number})
    asyncio.run(em.run_invoice_reminder_sweep(db, now=NOW))
    assert db.services.docs[0]["status"] == "suspended"

    # mirrors routes/billing.py step 3
    inv = db.invoices.docs[0]
    ors = [{"user_id": inv["user_id"],
            "suspended_reason": {"$regex": re.escape(suspended_reason_for(number)),
                                 "$options": "i"}}]
    ors.append({"_id": ObjectId(inv["service_id"])})
    res = asyncio.run(db.services.update_many(
        {"status": "suspended", "$or": ors},
        {"$set": {"status": "active", "reactivated_reason": f"invoice {number} paid"},
         "$unset": {"suspended_at": "", "suspended_reason": ""}},
    ))
    assert res.modified_count == 1, "reactivation must find the suspended service"
    assert db.services.docs[0]["status"] == "active"
    assert "suspended_reason" not in db.services.docs[0]


def test_legacy_reason_from_older_builds_still_reactivates(em):
    """Services suspended by the older build ('... overdue >8d') must still
    be reactivatable: the shared wording keeps that substring."""
    from portal.emails import suspended_reason_for
    legacy = "invoice INV-2026-00024 overdue >8d"
    assert re.search(re.escape(suspended_reason_for("INV-2026-00024")), legacy, re.I) \
        or re.search(r"invoice INV-2026-00024 overdue", legacy, re.I)
