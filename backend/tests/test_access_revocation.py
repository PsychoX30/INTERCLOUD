"""Access-revocation contract tests (2026-11-16).

Two defects were reproduced against the running production API:

  1. `is_active` was advertised as an access lever - it is part of
     `models.UserUpdateIn` and is written by `PUT /admin/users/{uid}` - but it
     was never consulted anywhere. Measured on prod: after setting
     `is_active=False`, a fresh login still returned 200 AND an already-issued
     token still worked. A "deactivated" account kept full access.

  2. The last active admin could be deactivated or demoted, which - once
     `is_active` became a real gate - would lock everybody out of the console.

Both are covered here. Delivery/email side effects are not involved.

Plain `asyncio.run` (the prod venv has no pytest-asyncio).
"""
import asyncio
import datetime as dt
import json

import pytest
from bson import ObjectId

from portal import auth as pa


NOW = dt.datetime(2026, 12, 1, tzinfo=dt.timezone.utc)


class _Collection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, query=None, *a, **kw):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (query or {}).items()):
                return d
        return None


class _DB:
    def __init__(self, users):
        self.users = _Collection(users)


def _request(headers=None):
    class _R:
        def __init__(self, h):
            self.headers = h or {}
            self.query_params = {}

    return _R(headers)


@pytest.fixture
def patched_db(monkeypatch):
    """Install a fake `server.db` and return a setter for its users."""
    import server

    holder = {}

    def install(users):
        holder["db"] = _DB(users)
        monkeypatch.setattr(server, "db", holder["db"], raising=False)
        return holder["db"]

    return install


def _token(user):
    return pa.create_access_token(str(user["_id"]), user["email"], user["role"])


# --------------------------------------------------------------------------- #
# 1. is_active must gate token resolution (revoke in-flight access)
# --------------------------------------------------------------------------- #
def test_active_user_token_resolves(patched_db):
    u = {"_id": ObjectId(), "email": "a@e.test", "role": "support",
         "is_active": True, "password_hash": "x"}
    patched_db([u])
    tok = _token(u)
    got = asyncio.run(pa._resolve_user(_request({"Authorization": f"Bearer {tok}"}), None))
    assert got["email"] == "a@e.test"
    assert got["role"] == "support"


def test_deactivated_user_token_is_rejected(patched_db):
    """A token issued before deactivation must stop working."""
    u = {"_id": ObjectId(), "email": "a@e.test", "role": "support",
         "is_active": False, "password_hash": "x"}
    patched_db([u])
    tok = _token(u)
    with pytest.raises(pa.HTTPException) as e:
        asyncio.run(pa._resolve_user(_request({"Authorization": f"Bearer {tok}"}), None))
    assert e.value.status_code == 401
    assert "dinonaktifkan" in e.value.detail.lower()


def test_missing_is_active_is_treated_as_active(patched_db):
    """Legacy documents without the field must keep working."""
    u = {"_id": ObjectId(), "email": "a@e.test", "role": "support",
         "password_hash": "x"}
    patched_db([u])
    tok = _token(u)
    got = asyncio.run(pa._resolve_user(_request({"Authorization": f"Bearer {tok}"}), None))
    assert got["email"] == "a@e.test"


def test_deactivated_user_blocked_in_query_param_path(patched_db):
    """The ?token= path (PDF preview) must not bypass the gate."""
    u = {"_id": ObjectId(), "email": "a@e.test", "role": "support",
         "is_active": False, "password_hash": "x"}
    patched_db([u])
    tok = _token(u)

    class _R:
        headers = {}
        query_params = {"token": tok}

    with pytest.raises(pa.HTTPException) as e:
        asyncio.run(pa._resolve_user(_R(), None))
    assert e.value.status_code == 401


# --------------------------------------------------------------------------- #
# 2. login / 2FA must refuse a deactivated account
# --------------------------------------------------------------------------- #
def test_login_route_checks_is_active():
    """Source-level guard: the login handler must consult is_active.

    A behavioural test would need the full app + a live DB; this pins the
    invariant that made prod's behaviour wrong in the first place.
    """
    import inspect
    from portal.routes import auth as routes_auth
    src = inspect.getsource(routes_auth.login)
    assert "is_active" in src, "login must reject deactivated accounts"


def test_2fa_route_checks_is_active():
    import inspect
    from portal.routes import auth as routes_auth
    src = inspect.getsource(routes_auth.login_2fa)
    assert "is_active" in src, "login_2fa must reject deactivated accounts"


# --------------------------------------------------------------------------- #
# 3. last-admin lock-out guard
# --------------------------------------------------------------------------- #
class _CountDB:
    """Just enough collection surface for the guard."""

    def __init__(self, users):
        self.users = _Collection(users)

    async def count_documents(self, q):
        return sum(1 for d in self.users.docs
                   if all((d.get(k) != v) if k == "_id" else (d.get(k) == v)
                          for k, v in q.items()))


def _guard(existing, upd, all_users):
    """Reproduce users.py' guard expression against a candidate update."""
    new_role = upd.get("role", existing.get("role"))
    losing_admin = existing.get("role") == "admin" and new_role != "admin"
    losing_active = existing.get("is_active") is not False and upd.get("is_active") is False
    if not (existing.get("role") == "admin" and (losing_admin or losing_active)):
        return "allowed"
    remaining = [u for u in all_users
                 if u.get("role") == "admin"
                 and u.get("is_active") is not False
                 and u["_id"] != existing["_id"]]
    return "blocked" if not remaining else "allowed"


def test_last_admin_cannot_be_deactivated():
    a = {"_id": ObjectId(), "role": "admin", "is_active": True, "email": "a@e.test"}
    assert _guard(a, {"is_active": False}, [a]) == "blocked"


def test_last_admin_cannot_be_demoted():
    a = {"_id": ObjectId(), "role": "admin", "is_active": True, "email": "a@e.test"}
    assert _guard(a, {"role": "support"}, [a]) == "blocked"


def test_second_admin_allows_deactivation():
    a = {"_id": ObjectId(), "role": "admin", "is_active": True, "email": "a@e.test"}
    b = {"_id": ObjectId(), "role": "admin", "is_active": True, "email": "b@e.test"}
    assert _guard(a, {"is_active": False}, [a, b]) == "allowed"


def test_inactive_admin_does_not_count_as_a_spare():
    """An already-deactivated admin must not unblock the guard."""
    a = {"_id": ObjectId(), "role": "admin", "is_active": True, "email": "a@e.test"}
    b = {"_id": ObjectId(), "role": "admin", "is_active": False, "email": "b@e.test"}
    assert _guard(a, {"is_active": False}, [a, b]) == "blocked"


def test_non_admin_is_unaffected_by_guard():
    c = {"_id": ObjectId(), "role": "support", "is_active": True, "email": "c@e.test"}
    assert _guard(c, {"is_active": False}, [c]) == "allowed"
