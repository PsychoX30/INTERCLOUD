"""Unified operations read-model endpoint.

This is the thin HTTP surface over ``portal.ops``. It exposes a single
read-only overview; every figure is derived from the owning module's data,
so this route owns no collection and writes nothing.
"""
from fastapi import APIRouter, Depends

from ..auth import require_roles, require_menu
from ..ops import build_ops_overview
from .shared import _get_db

router = APIRouter()


@router.get("/admin/ops/overview")
async def ops_overview(staff=Depends(require_menu("operations_center"))):
    """Unified operations snapshot (monitoring, NOC, SLA, security, audit).

    Read-only: no inserts, updates, dispatches, or side effects. Missing or
    unreadable counters are returned as ``null`` so the client can render
    "unknown" rather than a confident zero.

    ``role`` is forwarded only so the attention rows link to a console tab the
    caller may actually open; it does not change any counter.
    """
    db = await _get_db()
    return await build_ops_overview(db, role=staff.get("role") or "admin")
