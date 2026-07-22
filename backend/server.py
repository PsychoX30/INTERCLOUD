"""Intercloud Portal — FastAPI backend.

Modules:
- Auth (JWT + bcrypt): register/login/logout/me/forgot/reset
- Categories, Locations (CRUD)
- Assets (CRUD with straight-line depreciation)
- Reports (aggregated numbers, timeline)
- Users (admin only)
- Dashboard (KPI summary)

CAPTCHA (Cloudflare Turnstile) verification is present as a placeholder middleware
that runs only when TURNSTILE_ENABLED=true.
"""
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import os
import uuid
import logging
import secrets
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional, Literal, Any

import bcrypt
import jwt
import httpx
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, Query, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator

from depreciation import compute_depreciation, build_schedule

# ---------------------------------------------------------------- setup ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("intercloud")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALG = "HS256"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@intercloud.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
TURNSTILE_ENABLED = os.environ.get("TURNSTILE_ENABLED", "false").lower() == "true"
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET_KEY", "")

client = AsyncIOMotorClient(MONGO_URL, tz_aware=True, tzinfo=timezone.utc)
db = client[DB_NAME]

app = FastAPI(title="Intercloud Portal API", version="1.0.0")
api = APIRouter(prefix="/api")

# ---------------------------------------------------------------- utils ----
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": now_utc() + timedelta(hours=8),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id, "type": "refresh", "exp": now_utc() + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax", max_age=8 * 3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=False, samesite="lax", max_age=7 * 24 * 3600, path="/")


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


def serialize_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "email": doc["email"],
        "name": doc.get("name", ""),
        "role": doc.get("role", "staff"),
        "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at"),
    }


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


async def verify_turnstile(token: Optional[str], remote_ip: Optional[str]) -> None:
    """Verify Cloudflare Turnstile token. No-op when disabled."""
    if not TURNSTILE_ENABLED:
        return
    if not token:
        raise HTTPException(status_code=400, detail="CAPTCHA token required")
    if not TURNSTILE_SECRET:
        raise HTTPException(status_code=500, detail="CAPTCHA server not configured")
    try:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            r = await hc.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": TURNSTILE_SECRET, "response": token, "remoteip": remote_ip or ""},
            )
            data = r.json()
            if not data.get("success"):
                raise HTTPException(status_code=400, detail="CAPTCHA verification failed")
    except HTTPException:
        raise
    except Exception as e:
        log.error("Turnstile error: %s", e)
        raise HTTPException(status_code=500, detail="CAPTCHA verification error")


# ---------------------------------------------------------------- models ---
class RegisterInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str = Field(min_length=1, max_length=120)
    captcha_token: Optional[str] = None


class LoginInput(BaseModel):
    email: EmailStr
    password: str
    captcha_token: Optional[str] = None


class ForgotPasswordInput(BaseModel):
    email: EmailStr
    captcha_token: Optional[str] = None


class ResetPasswordInput(BaseModel):
    token: str
    new_password: str = Field(min_length=6)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: Optional[str] = None
    description: Optional[str] = None


class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: Optional[str] = None
    address: Optional[str] = None


class AssetIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    category_id: Optional[str] = None
    location_id: Optional[str] = None
    acquisition_cost: float = Field(ge=0)
    salvage_value: float = Field(ge=0)
    useful_life_years: int = Field(ge=1, le=100)
    acquisition_date: str  # ISO date "YYYY-MM-DD"
    status: Literal["active", "disposed", "in_repair"] = "active"
    notes: Optional[str] = None

    @field_validator("acquisition_date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        datetime.fromisoformat(v)
        return v


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[Literal["admin", "staff"]] = None
    password: Optional[str] = None


# ---------------------------------------------------------------- serializers
def serialize_category(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "code": doc.get("code"),
        "description": doc.get("description"),
        "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at"),
    }


def serialize_location(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "code": doc.get("code"),
        "address": doc.get("address"),
        "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at"),
    }


def serialize_asset(doc: dict, category: Optional[dict] = None, location: Optional[dict] = None) -> dict:
    dep = compute_depreciation(
        acquisition_cost=doc["acquisition_cost"],
        salvage_value=doc["salvage_value"],
        useful_life_years=doc["useful_life_years"],
        acquisition_date=doc["acquisition_date"],
    )
    return {
        "id": str(doc["_id"]),
        "code": doc["code"],
        "name": doc["name"],
        "category_id": doc.get("category_id"),
        "category_name": category["name"] if category else None,
        "location_id": doc.get("location_id"),
        "location_name": location["name"] if location else None,
        "acquisition_cost": doc["acquisition_cost"],
        "salvage_value": doc["salvage_value"],
        "useful_life_years": doc["useful_life_years"],
        "acquisition_date": doc["acquisition_date"],
        "status": doc.get("status", "active"),
        "notes": doc.get("notes"),
        "created_at": doc.get("created_at").isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at"),
        "depreciation": dep,
    }


# ---------------------------------------------------------------- startup --
@app.on_event("startup")
async def on_startup():
    # Indexes
    await db.users.create_index("email", unique=True)
    await db.categories.create_index("name", unique=True)
    await db.locations.create_index("name", unique=True)
    await db.assets.create_index("code", unique=True)
    await db.assets.create_index("category_id")
    await db.assets.create_index("location_id")
    await db.assets.create_index("acquisition_date")
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)

    # Seed admin
    existing = await db.users.find_one({"email": ADMIN_EMAIL})
    if not existing:
        await db.users.insert_one({
            "email": ADMIN_EMAIL,
            "password_hash": hash_password(ADMIN_PASSWORD),
            "name": "Administrator",
            "role": "admin",
            "created_at": now_utc(),
        })
        log.info("Admin seeded: %s", ADMIN_EMAIL)
    else:
        if not verify_password(ADMIN_PASSWORD, existing["password_hash"]):
            await db.users.update_one({"_id": existing["_id"]}, {"$set": {"password_hash": hash_password(ADMIN_PASSWORD)}})
            log.info("Admin password rotated")

    # Seed default taxonomy for a friendly first-run
    if await db.categories.count_documents({}) == 0:
        await db.categories.insert_many([
            {"name": "Kendaraan", "code": "VEH", "description": "Kendaraan operasional", "created_at": now_utc()},
            {"name": "Peralatan Kantor", "code": "OFF", "description": "Peralatan kantor & meubel", "created_at": now_utc()},
            {"name": "Komputer & IT", "code": "IT", "description": "Perangkat komputer dan IT", "created_at": now_utc()},
            {"name": "Mesin", "code": "MCH", "description": "Mesin produksi", "created_at": now_utc()},
            {"name": "Bangunan", "code": "BLD", "description": "Bangunan dan gedung", "created_at": now_utc()},
        ])
    if await db.locations.count_documents({}) == 0:
        await db.locations.insert_many([
            {"name": "Kantor Pusat", "code": "HQ", "address": "Jakarta", "created_at": now_utc()},
            {"name": "Gudang Utama", "code": "WH1", "address": "Bekasi", "created_at": now_utc()},
            {"name": "Cabang Bandung", "code": "BDG", "address": "Bandung", "created_at": now_utc()},
        ])


@app.on_event("shutdown")
async def on_shutdown():
    client.close()


# ---------------------------------------------------------------- auth -----
@api.get("/health")
async def health():
    return {"status": "ok", "time": to_iso(now_utc())}


@api.get("/auth/config")
async def auth_config():
    return {
        "turnstile_enabled": TURNSTILE_ENABLED,
        "turnstile_site_key": os.environ.get("TURNSTILE_SITE_KEY", ""),  # server-visible optional
    }


@api.post("/auth/register")
async def register(payload: RegisterInput, request: Request, response: Response):
    await verify_turnstile(payload.captcha_token, request.client.host if request.client else None)
    email = payload.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_doc = {
        "email": email,
        "password_hash": hash_password(payload.password),
        "name": payload.name.strip(),
        "role": "staff",
        "created_at": now_utc(),
    }
    result = await db.users.insert_one(user_doc)
    user_doc["_id"] = result.inserted_id
    access = create_access_token(str(result.inserted_id), email, "staff")
    refresh = create_refresh_token(str(result.inserted_id))
    set_auth_cookies(response, access, refresh)
    return {"user": serialize_user(user_doc), "access_token": access}


@api.post("/auth/login")
async def login(payload: LoginInput, request: Request, response: Response):
    await verify_turnstile(payload.captcha_token, request.client.host if request.client else None)
    email = payload.email.lower().strip()
    # Prefer forwarded IP from ingress; fall back to peer IP. Use email as
    # the identity anchor so throttling works even when ingress IPs rotate.
    fwd = request.headers.get("x-forwarded-for", "")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))
    identifier = email

    # Brute force check
    attempt = await db.login_attempts.find_one({"identifier": identifier})
    if attempt and attempt.get("locked_until") and attempt["locked_until"] > now_utc():
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        # Increment attempts (do NOT reset counter when locking so lockout persists)
        attempts = (attempt.get("count", 0) if attempt else 0) + 1
        update = {"identifier": identifier, "count": attempts, "last_at": now_utc(), "last_ip": ip}
        if attempts >= 5:
            update["locked_until"] = now_utc() + timedelta(minutes=15)
        await db.login_attempts.update_one({"identifier": identifier}, {"$set": update}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await db.login_attempts.delete_one({"identifier": identifier})
    uid = str(user["_id"])
    access = create_access_token(uid, email, user.get("role", "staff"))
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return {"user": serialize_user(user), "access_token": access}


@api.post("/auth/logout")
async def logout(response: Response, _: dict = Depends(get_current_user)):
    clear_auth_cookies(response)
    return {"ok": True}


@api.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return serialize_user(user)


@api.post("/auth/refresh")
async def refresh_token(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access = create_access_token(str(user["_id"]), user["email"], user.get("role", "staff"))
        response.set_cookie("access_token", access, httponly=True, secure=False, samesite="lax", max_age=8 * 3600, path="/")
        return {"access_token": access}
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")


@api.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordInput, request: Request):
    await verify_turnstile(payload.captcha_token, request.client.host if request.client else None)
    email = payload.email.lower().strip()
    user = await db.users.find_one({"email": email})
    # Always return success to avoid email enumeration
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": str(user["_id"]),
            "expires_at": now_utc() + timedelta(hours=1),
            "used": False,
            "created_at": now_utc(),
        })
        log.info("Password reset for %s: %s", email, token)
        return {"ok": True, "reset_token": token}  # dev-friendly: include token
    return {"ok": True}


@api.post("/auth/reset-password")
async def reset_password(payload: ResetPasswordInput):
    rec = await db.password_reset_tokens.find_one({"token": payload.token})
    if not rec or rec.get("used") or rec["expires_at"] < now_utc():
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    await db.users.update_one({"_id": ObjectId(rec["user_id"])}, {"$set": {"password_hash": hash_password(payload.new_password)}})
    await db.password_reset_tokens.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return {"ok": True}


# ---------------------------------------------------------------- taxonomy -
@api.get("/categories")
async def list_categories(_: dict = Depends(get_current_user)):
    docs = await db.categories.find().sort("name", 1).to_list(1000)
    return [serialize_category(d) for d in docs]


@api.post("/categories")
async def create_category(payload: CategoryIn, _: dict = Depends(require_admin)):
    if await db.categories.find_one({"name": payload.name}):
        raise HTTPException(status_code=400, detail="Category name already exists")
    doc = {**payload.model_dump(), "created_at": now_utc()}
    r = await db.categories.insert_one(doc)
    doc["_id"] = r.inserted_id
    return serialize_category(doc)


@api.put("/categories/{cid}")
async def update_category(cid: str, payload: CategoryIn, _: dict = Depends(require_admin)):
    r = await db.categories.update_one({"_id": ObjectId(cid)}, {"$set": payload.model_dump()})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.categories.find_one({"_id": ObjectId(cid)})
    return serialize_category(doc)


@api.delete("/categories/{cid}")
async def delete_category(cid: str, _: dict = Depends(require_admin)):
    in_use = await db.assets.count_documents({"category_id": cid})
    if in_use:
        raise HTTPException(status_code=400, detail=f"Category used by {in_use} asset(s)")
    await db.categories.delete_one({"_id": ObjectId(cid)})
    return {"ok": True}


@api.get("/locations")
async def list_locations(_: dict = Depends(get_current_user)):
    docs = await db.locations.find().sort("name", 1).to_list(1000)
    return [serialize_location(d) for d in docs]


@api.post("/locations")
async def create_location(payload: LocationIn, _: dict = Depends(require_admin)):
    if await db.locations.find_one({"name": payload.name}):
        raise HTTPException(status_code=400, detail="Location name already exists")
    doc = {**payload.model_dump(), "created_at": now_utc()}
    r = await db.locations.insert_one(doc)
    doc["_id"] = r.inserted_id
    return serialize_location(doc)


@api.put("/locations/{lid}")
async def update_location(lid: str, payload: LocationIn, _: dict = Depends(require_admin)):
    r = await db.locations.update_one({"_id": ObjectId(lid)}, {"$set": payload.model_dump()})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.locations.find_one({"_id": ObjectId(lid)})
    return serialize_location(doc)


@api.delete("/locations/{lid}")
async def delete_location(lid: str, _: dict = Depends(require_admin)):
    in_use = await db.assets.count_documents({"location_id": lid})
    if in_use:
        raise HTTPException(status_code=400, detail=f"Location used by {in_use} asset(s)")
    await db.locations.delete_one({"_id": ObjectId(lid)})
    return {"ok": True}


# ---------------------------------------------------------------- assets ---
async def _lookup_taxonomy(category_id: Optional[str], location_id: Optional[str]):
    cat = await db.categories.find_one({"_id": ObjectId(category_id)}) if category_id else None
    loc = await db.locations.find_one({"_id": ObjectId(location_id)}) if location_id else None
    return cat, loc


@api.get("/assets")
async def list_assets(
    _: dict = Depends(get_current_user),
    q: Optional[str] = Query(None),
    category_id: Optional[str] = None,
    location_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = 1,
    page_size: int = 20,
):
    filt: dict = {}
    if q:
        filt["$or"] = [{"code": {"$regex": q, "$options": "i"}}, {"name": {"$regex": q, "$options": "i"}}]
    if category_id:
        filt["category_id"] = category_id
    if location_id:
        filt["location_id"] = location_id
    if status_filter:
        filt["status"] = status_filter

    total = await db.assets.count_documents(filt)
    cursor = db.assets.find(filt).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size)
    docs = await cursor.to_list(page_size)

    # Batch load taxonomy
    cat_ids = list({d.get("category_id") for d in docs if d.get("category_id")})
    loc_ids = list({d.get("location_id") for d in docs if d.get("location_id")})
    cats = {}
    if cat_ids:
        async for c in db.categories.find({"_id": {"$in": [ObjectId(i) for i in cat_ids]}}):
            cats[str(c["_id"])] = c
    locs = {}
    if loc_ids:
        async for l in db.locations.find({"_id": {"$in": [ObjectId(i) for i in loc_ids]}}):
            locs[str(l["_id"])] = l

    items = [
        serialize_asset(d, cats.get(d.get("category_id")), locs.get(d.get("location_id")))
        for d in docs
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@api.post("/assets")
async def create_asset(payload: AssetIn, _: dict = Depends(get_current_user)):
    if await db.assets.find_one({"code": payload.code}):
        raise HTTPException(status_code=400, detail="Asset code already exists")
    doc = payload.model_dump()
    doc["created_at"] = now_utc()
    r = await db.assets.insert_one(doc)
    doc["_id"] = r.inserted_id
    cat, loc = await _lookup_taxonomy(doc.get("category_id"), doc.get("location_id"))
    return serialize_asset(doc, cat, loc)


@api.get("/assets/{aid}")
async def get_asset(aid: str, _: dict = Depends(get_current_user)):
    doc = await db.assets.find_one({"_id": ObjectId(aid)})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    cat, loc = await _lookup_taxonomy(doc.get("category_id"), doc.get("location_id"))
    payload = serialize_asset(doc, cat, loc)
    payload["schedule"] = build_schedule(
        doc["acquisition_cost"], doc["salvage_value"], doc["useful_life_years"], doc["acquisition_date"]
    )
    return payload


@api.put("/assets/{aid}")
async def update_asset(aid: str, payload: AssetIn, _: dict = Depends(get_current_user)):
    existing = await db.assets.find_one({"_id": ObjectId(aid)})
    if not existing:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.code != existing["code"] and await db.assets.find_one({"code": payload.code}):
        raise HTTPException(status_code=400, detail="Asset code already exists")
    await db.assets.update_one({"_id": ObjectId(aid)}, {"$set": payload.model_dump()})
    doc = await db.assets.find_one({"_id": ObjectId(aid)})
    cat, loc = await _lookup_taxonomy(doc.get("category_id"), doc.get("location_id"))
    return serialize_asset(doc, cat, loc)


@api.delete("/assets/{aid}")
async def delete_asset(aid: str, _: dict = Depends(require_admin)):
    r = await db.assets.delete_one({"_id": ObjectId(aid)})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---------------------------------------------------------------- users ----
@api.get("/users")
async def list_users(_: dict = Depends(require_admin)):
    docs = await db.users.find().sort("created_at", -1).to_list(500)
    return [serialize_user(d) for d in docs]


@api.put("/users/{uid}")
async def update_user(uid: str, payload: UserUpdateIn, admin: dict = Depends(require_admin)):
    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.role is not None:
        updates["role"] = payload.role
    if payload.password:
        updates["password_hash"] = hash_password(payload.password)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update")
    r = await db.users.update_one({"_id": ObjectId(uid)}, {"$set": updates})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.users.find_one({"_id": ObjectId(uid)})
    return serialize_user(doc)


@api.delete("/users/{uid}")
async def delete_user(uid: str, admin: dict = Depends(require_admin)):
    if str(admin["_id"]) == uid:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    r = await db.users.delete_one({"_id": ObjectId(uid)})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ---------------------------------------------------------------- dashboard
@api.get("/dashboard/summary")
async def dashboard_summary(_: dict = Depends(get_current_user)):
    total_assets = await db.assets.count_documents({})
    active_assets = await db.assets.count_documents({"status": "active"})

    total_cost = 0.0
    total_acc_dep = 0.0
    total_book = 0.0
    by_cat: dict[str, dict] = {}
    by_loc: dict[str, dict] = {}
    by_status: dict[str, int] = {}

    async for d in db.assets.find():
        dep = compute_depreciation(
            d["acquisition_cost"], d["salvage_value"], d["useful_life_years"], d["acquisition_date"]
        )
        total_cost += d["acquisition_cost"]
        total_acc_dep += dep["accumulated_depreciation"]
        total_book += dep["book_value"]
        cid = d.get("category_id") or "uncategorized"
        by_cat.setdefault(cid, {"acquisition_cost": 0, "book_value": 0, "count": 0})
        by_cat[cid]["acquisition_cost"] += d["acquisition_cost"]
        by_cat[cid]["book_value"] += dep["book_value"]
        by_cat[cid]["count"] += 1
        lid = d.get("location_id") or "unassigned"
        by_loc.setdefault(lid, {"acquisition_cost": 0, "book_value": 0, "count": 0})
        by_loc[lid]["acquisition_cost"] += d["acquisition_cost"]
        by_loc[lid]["book_value"] += dep["book_value"]
        by_loc[lid]["count"] += 1
        s = d.get("status", "active")
        by_status[s] = by_status.get(s, 0) + 1

    # resolve category/location names
    async def _name_map(collection, ids):
        out = {}
        real_ids = [i for i in ids if i not in {"uncategorized", "unassigned"}]
        if real_ids:
            async for x in collection.find({"_id": {"$in": [ObjectId(i) for i in real_ids]}}):
                out[str(x["_id"])] = x["name"]
        return out

    cat_names = await _name_map(db.categories, list(by_cat.keys()))
    loc_names = await _name_map(db.locations, list(by_loc.keys()))

    category_breakdown = [
        {"id": cid, "name": cat_names.get(cid, "Tanpa Kategori" if cid == "uncategorized" else "?"), **vals}
        for cid, vals in by_cat.items()
    ]
    location_breakdown = [
        {"id": lid, "name": loc_names.get(lid, "Tanpa Lokasi" if lid == "unassigned" else "?"), **vals}
        for lid, vals in by_loc.items()
    ]

    return {
        "total_assets": total_assets,
        "active_assets": active_assets,
        "total_acquisition_cost": round(total_cost, 2),
        "total_accumulated_depreciation": round(total_acc_dep, 2),
        "total_book_value": round(total_book, 2),
        "category_breakdown": category_breakdown,
        "location_breakdown": location_breakdown,
        "status_breakdown": by_status,
    }


# ---------------------------------------------------------------- reports --
@api.get("/reports/depreciation")
async def report_depreciation(
    _: dict = Depends(get_current_user),
    as_of: Optional[str] = Query(None, description="ISO date, default = today"),
    category_id: Optional[str] = None,
    location_id: Optional[str] = None,
):
    filt: dict = {}
    if category_id:
        filt["category_id"] = category_id
    if location_id:
        filt["location_id"] = location_id
    ref = date.fromisoformat(as_of) if as_of else date.today()

    cat_ids: set = set()
    loc_ids: set = set()
    rows = []
    async for d in db.assets.find(filt):
        dep = compute_depreciation(
            d["acquisition_cost"], d["salvage_value"], d["useful_life_years"], d["acquisition_date"], as_of=ref
        )
        rows.append({
            "id": str(d["_id"]),
            "code": d["code"],
            "name": d["name"],
            "category_id": d.get("category_id"),
            "location_id": d.get("location_id"),
            "acquisition_date": d["acquisition_date"],
            "acquisition_cost": d["acquisition_cost"],
            "salvage_value": d["salvage_value"],
            "useful_life_years": d["useful_life_years"],
            "annual_depreciation": dep["annual_depreciation"],
            "accumulated_depreciation": dep["accumulated_depreciation"],
            "book_value": dep["book_value"],
        })
        if d.get("category_id"):
            cat_ids.add(d["category_id"])
        if d.get("location_id"):
            loc_ids.add(d["location_id"])

    cat_names = {}
    async for c in db.categories.find({"_id": {"$in": [ObjectId(i) for i in cat_ids]}}):
        cat_names[str(c["_id"])] = c["name"]
    loc_names = {}
    async for l in db.locations.find({"_id": {"$in": [ObjectId(i) for i in loc_ids]}}):
        loc_names[str(l["_id"])] = l["name"]
    for r in rows:
        r["category_name"] = cat_names.get(r["category_id"]) if r["category_id"] else None
        r["location_name"] = loc_names.get(r["location_id"]) if r["location_id"] else None

    totals = {
        "acquisition_cost": round(sum(r["acquisition_cost"] for r in rows), 2),
        "accumulated_depreciation": round(sum(r["accumulated_depreciation"] for r in rows), 2),
        "book_value": round(sum(r["book_value"] for r in rows), 2),
    }
    return {"as_of": ref.isoformat(), "rows": rows, "totals": totals}


@api.get("/reports/timeline")
async def report_timeline(_: dict = Depends(get_current_user), years: int = 5):
    """Yearly forecast of aggregate accumulated depreciation & book value."""
    ref_year = date.today().year
    year_list = list(range(ref_year - 1, ref_year + years))
    points = {y: {"year": y, "accumulated_depreciation": 0.0, "book_value": 0.0} for y in year_list}
    async for d in db.assets.find():
        for y in year_list:
            dep = compute_depreciation(
                d["acquisition_cost"], d["salvage_value"], d["useful_life_years"], d["acquisition_date"],
                as_of=date(y, 12, 31),
            )
            points[y]["accumulated_depreciation"] += dep["accumulated_depreciation"]
            points[y]["book_value"] += dep["book_value"]
    series = [
        {"year": p["year"],
         "accumulated_depreciation": round(p["accumulated_depreciation"], 2),
         "book_value": round(p["book_value"], 2)}
        for p in points.values()
    ]
    return {"series": series}


# ---------------------------------------------------------------- mount ----
app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
