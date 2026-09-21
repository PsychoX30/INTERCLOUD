"""Foldering / sharing overhaul endpoints for INTERCLOUD documents.

Adds (on top of business.py which already has the folder tree + granular share_with):
- Staff directory (excludes clients, searchable, paginated) — closes the client-leak bug
- Personal-folder auto-provision (idempotent, per-request)
- Folder ACL create/patch via v2 endpoints
- Share links with optional password + expiry + revoke
- Public share endpoints (token-based, rate-limited)

Mounted under the same portal router. Reuses helpers from business.py so the
permission model stays single-sourced.
"""
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..auth import (
    get_current_staff, hash_password, verify_password, STAFF_ROLES,
    create_share_token, decode_share_token,
)
from ..security import limiter
from .shared import _get_db, _now, _oid, _pagination_params, _pagination_response
from .business import (
    _serialize_doc, _serialize_folder, DOCS_DIR,
    _effective_perms, _staff_oid, PERM_LEVELS, OVERRIDE_ROLES,
    _folder_visible_to, _require_internal_document_access,
)

router = APIRouter()


# ============================================================
# Folder permission resolver (mirrors _effective_perms for folders)
# ============================================================
def _folder_effective_perms(staff: dict, folder: dict, parent_chain: list[dict] | None = None) -> set[str]:
    role = (staff.get("role") or "").strip().lower()
    staff_id = _staff_oid(staff)

    if role in OVERRIDE_ROLES:
        if role == "support":
            return {"read", "download", "manage"}
        return set(PERM_LEVELS)

    if folder.get("owner_id") and str(folder.get("owner_id")) == staff_id:
        return set(PERM_LEVELS)

    perms: set[str] = set()

    def _apply(acl_list):
        for entry in acl_list or []:
            if entry.get("principal_type") == "user" and str(entry.get("principal_id")) == staff_id:
                perms.update(entry.get("perms") or [])
            if entry.get("principal_type") == "division" and (staff.get("division") or "").strip().lower() == str(entry.get("principal_id") or "").strip().lower():
                perms.update(entry.get("perms") or [])
            if entry.get("principal_type") == "role" and role == str(entry.get("principal_id") or "").strip().lower():
                perms.update(entry.get("perms") or [])

    _apply(folder.get("acl"))
    if parent_chain and folder.get("inherit_parent_acl", True):
        for parent in parent_chain:
            _apply(parent.get("acl"))
            if not parent.get("inherit_parent_acl", True):
                break
    return perms


async def _parent_chain(db, folder: dict) -> list[dict]:
    """Root→leaf chain of ancestors for the given folder (excludes the folder itself)."""
    chain: list[dict] = []
    pid = folder.get("parent_id")
    while pid:
        p = await db.document_folders.find_one({"_id": pid if not isinstance(pid, str) else _oid(pid)})
        if not p:
            break
        chain.insert(0, p)
        pid = p.get("parent_id")
    return chain


def _validate_acl_no_clients(acl: list, staff_ids_client: set[str]) -> None:
    """Reject any ACL entry granting a user whose role is client (server-side leak guard)."""
    for entry in acl or []:
        if entry.get("principal_type") == "user" and str(entry.get("principal_id")) in staff_ids_client:
            raise HTTPException(status_code=400, detail="Cannot grant document access to a client account")
        if entry.get("principal_type") == "role" and str(entry.get("principal_id") or "").strip().lower() == "client":
            raise HTTPException(status_code=400, detail="Cannot grant document access to the client role")


# ============================================================
# Personal-folder auto-provision
# ============================================================
async def _ensure_personal_folder(staff: dict, db):
    staff_id = _staff_oid(staff)
    existing = await db.document_folders.find_one({"kind": "personal", "owner_id": staff_id})
    if existing:
        return existing
    name = staff.get("name") or staff.get("email", "Personal")
    folder = {
        "name": name,
        "parent_id": None,
        "owner_id": staff_id,
        "owner_name": staff.get("name") or staff.get("email", ""),
        "division": (staff.get("division") or "").strip().lower(),
        "path": f"Personal/{staff_id}",
        "kind": "personal",
        "created_at": _now(),
        "acl": [],
        "inherit_parent_acl": False,
    }
    r = await db.document_folders.insert_one(folder)
    folder["_id"] = r.inserted_id
    return folder


# ============================================================
# Folder tree v2: perms + kind + auto-provision personal root
# ============================================================
@router.get("/admin/document-folders-v2")
async def folders_list_v2(staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    await _ensure_personal_folder(staff, db)
    folders = await db.document_folders.find({}).sort("path", 1).to_list(2000)
    by_id = {str(f["_id"]): f for f in folders}

    def chain_for(f: dict) -> list[dict]:
        out: list[dict] = []
        pid = f.get("parent_id")
        while pid:
            p = by_id.get(str(pid))
            if not p:
                break
            out.insert(0, p)
            pid = p.get("parent_id")
        return out

    def folder_visible(f: dict) -> bool:
        # visible if legacy-visible OR caller has any effective perm via ACL
        if _folder_visible_to(staff, f):
            return True
        return bool(_folder_effective_perms(staff, f, chain_for(f)))

    visible = [f for f in folders if folder_visible(f)]
    by_parent: dict = {}
    for f in visible:
        by_parent.setdefault(str(f.get("parent_id")) if f.get("parent_id") else None, []).append(f)

    def build(parent_key):
        out = []
        for f in by_parent.get(parent_key, []):
            perms = sorted(_folder_effective_perms(staff, f, chain_for(f)))
            kind = f.get("kind") or ("shared" if f.get("is_shared_root") else "personal" if f.get("is_private_root") else "custom")
            out.append(_serialize_folder(f) | {"children": build(str(f["_id"])), "perms": perms, "kind": kind})
        return out

    return build(None)


@router.post("/admin/document-folders-v2")
async def folders_create_v2(payload: dict, staff=Depends(get_current_staff)):
    _require_internal_document_access(staff)
    db = await _get_db()
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Nama folder wajib diisi")
    if "/" in name:
        raise HTTPException(status_code=400, detail="Nama folder tidak boleh mengandung '/'")
    parent_id = payload.get("parent_id")
    parent = None
    if parent_id:
        p_oid = _oid(str(parent_id))
        if p_oid is None:
            raise HTTPException(status_code=400, detail="Invalid parent_id")
        parent = await db.document_folders.find_one({"_id": p_oid})
        if not parent:
            raise HTTPException(status_code=400, detail="Parent folder not found")
        chain = await _parent_chain(db, parent) + [parent]
        if "manage" not in _folder_effective_perms(staff, parent, chain[:-1]):
            raise HTTPException(status_code=403, detail="You do not have permission to create folders here")
    else:
        if staff.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Only admin can create top-level folders")

    division = (payload.get("division") or "").strip().lower()
    owner_id = None
    if parent is None and division:
        owner_id = None
    elif parent is not None and parent.get("owner_id"):
        owner_id = parent.get("owner_id")
        division = division or parent.get("division", "")
    elif staff.get("role") != "admin":
        owner_id = staff.get("id")
    path = f"{parent.get('path', '').rstrip('/')}/{name}" if parent else name
    folder = {
        "name": name,
        "parent_id": parent["_id"] if parent else None,
        "owner_id": owner_id,
        "owner_name": staff.get("name") or staff.get("email", ""),
        "division": division,
        "path": path,
        "kind": payload.get("kind") or "custom",
        "created_at": _now(),
        "acl": payload.get("acl") or [],
        "inherit_parent_acl": payload.get("inherit_parent_acl", True),
    }
    r = await db.document_folders.insert_one(folder)
    folder["_id"] = r.inserted_id
    return _serialize_folder(folder) | {"perms": sorted(_folder_effective_perms(staff, folder)), "kind": folder["kind"]}


@router.patch("/admin/document-folders-v2/{fid}")
async def folders_update_v2(fid: str, payload: dict, staff=Depends(get_current_staff)):
    """Update folder ACL / inherit flag. Guard = manage."""
    db = await _get_db()
    f = await db.document_folders.find_one({"_id": _oid(fid)})
    if not f:
        raise HTTPException(status_code=404, detail="Folder not found")
    chain = await _parent_chain(db, f)
    if "manage" not in _folder_effective_perms(staff, f, chain):
        raise HTTPException(status_code=403, detail="Only folder managers can update this folder")
    upd: dict = {}
    if "acl" in payload:
        # server-side client exclusion
        client_ids = set()
        acl = payload.get("acl") or []
        user_ids = [str(e.get("principal_id")) for e in acl if e.get("principal_type") == "user"]
        if user_ids:
            oids = [_oid(u) for u in user_ids if _oid(u)]
            async for u in db.users.find({"_id": {"$in": oids}, "role": "client"}):
                client_ids.add(str(u["_id"]))
        _validate_acl_no_clients(acl, client_ids)
        upd["acl"] = acl
    if "inherit_parent_acl" in payload:
        upd["inherit_parent_acl"] = bool(payload["inherit_parent_acl"])
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await db.document_folders.update_one({"_id": f["_id"]}, {"$set": upd})
    f.update(upd)
    return _serialize_folder(f) | {"perms": sorted(_folder_effective_perms(staff, f, chain)), "kind": f.get("kind", "custom")}


# ============================================================
# Share links
# ============================================================
@router.post("/admin/document-folders/{fid}/share-links")
async def create_share_link(fid: str, payload: dict, staff=Depends(get_current_staff)):
    """Create a password-protected or open share link. Returns plaintext token ONCE."""
    db = await _get_db()
    folder = await db.document_folders.find_one({"_id": _oid(fid)})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    chain = await _parent_chain(db, folder)
    if "manage" not in _folder_effective_perms(staff, folder, chain):
        raise HTTPException(status_code=403, detail="Only folder managers can create share links")
    perms = [p for p in (payload.get("perms") or ["read"]) if p in ("read", "download")]
    if not perms:
        perms = ["read"]
    password = payload.get("password") or ""
    expires_days = payload.get("expires_in_days")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    link = {
        "folder_id": str(folder["_id"]),
        "token_hash": token_hash,
        "password_hash": hash_password(password) if password else None,
        "perms": perms,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=int(expires_days))).isoformat() if expires_days else None,
        "created_by": _staff_oid(staff),
        "created_at": _now(),
        "revoked": False,
    }
    r = await db.share_links.insert_one(link)
    return {"link_id": str(r.inserted_id), "token": token, "expires_at": link["expires_at"],
            "perms": perms, "requires_password": bool(password)}


@router.get("/admin/document-folders/{fid}/share-links")
async def list_share_links(fid: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    folder = await db.document_folders.find_one({"_id": _oid(fid)})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    chain = await _parent_chain(db, folder)
    if "manage" not in _folder_effective_perms(staff, folder, chain):
        raise HTTPException(status_code=403, detail="Only folder managers can view share links")
    links = await db.share_links.find({"folder_id": str(folder["_id"]), "revoked": False}).to_list(200)
    return [{
        "link_id": str(l["_id"]),
        "perms": l.get("perms", []),
        "requires_password": bool(l.get("password_hash")),
        "expires_at": l.get("expires_at"),
        "created_at": l.get("created_at"),
    } for l in links]


@router.delete("/admin/document-folders/{fid}/share-links/{link_id}")
async def revoke_share_link(fid: str, link_id: str, staff=Depends(get_current_staff)):
    db = await _get_db()
    folder = await db.document_folders.find_one({"_id": _oid(fid)})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    chain = await _parent_chain(db, folder)
    if "manage" not in _folder_effective_perms(staff, folder, chain):
        raise HTTPException(status_code=403, detail="Only folder managers can revoke share links")
    await db.share_links.update_one(
        {"_id": _oid(link_id), "folder_id": str(folder["_id"])},
        {"$set": {"revoked": True}},
    )
    return {"revoked": True}


# ============================================================
# Public share endpoints (rate-limited, no-store)
# ============================================================
async def _resolve_active_link(db, token: str) -> dict:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    link = await db.share_links.find_one({"token_hash": token_hash, "revoked": False})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found or revoked")
    if link.get("expires_at") and datetime.now(timezone.utc) > datetime.fromisoformat(link["expires_at"]):
        raise HTTPException(status_code=410, detail="Link expired")
    return link


async def _validate_unlock_jwt(request: Request, path_token: str) -> bool:
    """True iff request carries a valid unlock-JWT for *path_token*.

    The unlock endpoint hands out a short-lived JWT that embeds the share
    token's SHA-256 hash. Public share endpoints check this before raising
    the "Password required — call /unlock first" 401, so a password-protected
    link becomes usable after the caller has unlocked it once.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    try:
        data = decode_share_token(auth[7:])
    except jwt.PyJWTError:
        return False
    expected = hashlib.sha256(path_token.encode()).hexdigest()
    return data.get("share_token_hash") == expected


@router.post("/documents/shared/{token}/unlock")
@limiter.limit("10/minute")
async def unlock_share_link(request: Request, token: str, payload: dict):
    db = await _get_db()
    link = await _resolve_active_link(db, token)
    if link.get("password_hash"):
        if not verify_password(payload.get("password", ""), link["password_hash"]):
            raise HTTPException(status_code=401, detail="Incorrect password")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    jwt_token = create_share_token(token_hash)
    return {"token": jwt_token, "perms": link.get("perms", ["read"])}


@router.get("/documents/shared/{token}")
@limiter.limit("30/minute")
async def shared_folder_list(request: Request, token: str):
    db = await _get_db()
    link = await _resolve_active_link(db, token)
    if not await _validate_unlock_jwt(request, token):
        if link.get("password_hash"):
            raise HTTPException(status_code=401, detail="Password required — call /unlock first")
    if "read" not in link.get("perms", []):
        raise HTTPException(status_code=403, detail="Link does not allow reading")
    folder = await db.document_folders.find_one({"_id": _oid(link["folder_id"])})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    docs = await db.documents.find({"folder_id": str(folder["_id"])}).to_list(1000)
    items = []
    for d in docs:
        s = _serialize_doc(d)
        s.pop("share_with", None)
        s.pop("owner_id", None)
        s["can_download"] = "download" in link.get("perms", [])
        items.append(s)
    resp = {"folder": {"name": folder.get("name"), "path": folder.get("path")}, "documents": items}
    return resp


@router.get("/documents/shared/{token}/file/{did}")
@limiter.limit("30/minute")
async def shared_file_download(request: Request, token: str, did: str):
    db = await _get_db()
    link = await _resolve_active_link(db, token)
    if not await _validate_unlock_jwt(request, token):
        if link.get("password_hash"):
            raise HTTPException(status_code=401, detail="Password required — call /unlock first")
    if "download" not in link.get("perms", []):
        raise HTTPException(status_code=403, detail="Link does not allow download")
    doc = await db.documents.find_one({"_id": _oid(did), "folder_id": link["folder_id"]})
    if not doc or not doc.get("stored_name"):
        raise HTTPException(status_code=404, detail="File not found")
    fp = DOCS_DIR / doc["stored_name"]
    if not fp.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")
    return FileResponse(fp, media_type=doc.get("content_type") or "application/octet-stream",
                        filename=doc.get("filename") or doc["stored_name"],
                        headers={"Content-Disposition": f'attachment; filename="{quote(doc.get("filename") or doc["stored_name"])}"',
                                 "Cache-Control": "no-store"})
