"""Staff directory endpoint for document sharing picker (client-exclusion).

Adds /admin/staff-directory that:
- Returns internal staff only (role != client)
- Supports search, role/division filter, sort, pagination
- Prevents client-leak bug that could happen via /admin/users
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from ..auth import get_current_staff, STAFF_ROLES
from .shared import _get_db, _pagination_params, _pagination_response

router = APIRouter()


@router.get("/admin/staff-directory")
async def staff_directory(
    staff=Depends(get_current_staff),
    q: Optional[str] = None,
    role: Optional[str] = None,
    division: Optional[str] = None,
    sort: str = "name",
    order: str = "asc",
    skip: int = 0,
    limit: int = 50,
):
    """Return internal staff excluding clients. Supports search, filter, sort, pagination."""
    db = await _get_db()
    query: dict = {"role": {"$in": list(STAFF_ROLES - {"client"})}}

    if role:
        r = role.strip().lower()
        if r == "client":
            raise HTTPException(status_code=400, detail="Clients are not selectable")
        query["role"] = r

    if division:
        query["division"] = division.strip().lower()

    if q:
        regex = {"$regex": q.strip(), "$options": "i"}
        query["$and"] = [{"$or": [{"name": regex}, {"email": regex}]}]

    sort_field = sort if sort in {"name", "email", "role", "division", "created_at"} else "name"
    direction = 1 if order.lower() == "asc" else -1

    skip_n, limit_n = _pagination_params(skip, limit)
    cursor = db.users.find(query).sort(sort_field, direction).skip(skip_n)
    if limit_n is not None:
        cursor = cursor.limit(limit_n)

    items = []
    async for u in cursor:
        items.append({
            "id": str(u["_id"]),
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "role": u.get("role", ""),
            "division": u.get("division", ""),
        })

    total = await db.users.count_documents(query)
    return _pagination_response(items, total, skip_n, limit_n, True)


@router.get("/admin/staff-directory/users")
async def staff_directory_users(
    staff=Depends(get_current_staff),
    q: Optional[str] = None,
    role: Optional[str] = None,
    division: Optional[str] = None,
):
    """Flat array for picker dropdown (excludes clients)."""
    db = await _get_db()
    query: dict = {"role": {"$in": list(STAFF_ROLES - {"client"})}}

    if role:
        r = role.strip().lower()
        if r == "client":
            raise HTTPException(status_code=400, detail="Clients are not selectable")
        query["role"] = r

    if division:
        query["division"] = division.strip().lower()

    if q:
        regex = {"$regex": q.strip(), "$options": "i"}
        query["$and"] = [{"$or": [{"name": regex}, {"email": regex}]}]

    cursor = db.users.find(query).sort("name", 1).limit(200)
    items = []
    async for u in cursor:
        items.append({
            "id": str(u["_id"]),
            "name": u.get("name", ""),
            "email": u.get("email", ""),
        })
    return {"items": items}
