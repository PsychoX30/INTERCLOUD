from fastapi import FastAPI, APIRouter, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from portal.security import (
    limiter, SecurityHeadersMiddleware, install_log_filter, log_csp_report,
)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Wire the shared slowapi limiter (defined in portal/security.py)
app.state.limiter = limiter

async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return Response(
        content='{"detail":"Too many requests. Please slow down and try again shortly."}',
        status_code=429, media_type="application/json",
        headers={"Retry-After": "60"},
    )

app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


@api_router.get("/")
async def root():
    return {"message": "Hello World"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    _ = await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    return status_checks


# Include the base router
app.include_router(api_router)

# ---------- PORTAL ROUTES ----------
from portal.routes import router as portal_router  # noqa: E402
app.include_router(portal_router)


# GZip large JSON payloads — added FIRST (innermost) so it sees the raw response
# from the app before any BaseHTTPMiddleware (SlowAPI, SecurityHeaders) wraps
# it in a streaming form. Otherwise GZipResponder never respects minimum_size.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Slowapi rate-limit middleware (checks decorated routes)
app.add_middleware(SlowAPIMiddleware)

# Security headers (HSTS, X-Frame-Options, CSP report-only, …) — sits outside
# GZip so its BaseHTTPMiddleware body-wrapping happens after compression.
app.add_middleware(SecurityHeadersMiddleware)

# CORS — read whitelist from env; blanks fall through to a single-line "*"
_cors_raw = os.environ.get('CORS_ORIGINS', '*').strip()
_cors_origins = [o.strip() for o in _cors_raw.split(',') if o.strip()] or ['*']
app.add_middleware(
    CORSMiddleware,
    allow_credentials=(_cors_origins != ['*']),
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSP violation reporter (report-only mode → browsers POST here)
@app.post("/api/csp-report")
async def csp_report(request: Request):
    body = await request.body()
    await log_csp_report(body)
    return Response(status_code=204)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Mask JWT/bearer/password/token/email in log lines
install_log_filter()


@app.on_event("startup")
async def startup_seed():
    try:
        await db.users.create_index("email", unique=True)
        await db.invoices.create_index("number", unique=True)
        await db.tickets.create_index("number", unique=True)
        await db.quotations.create_index("number", unique=True)
        # login_attempts: index by timestamp for range queries; auto-drop docs after 90 days
        await db.login_attempts.create_index("created_at")
        await db.login_attempts.create_index("email")
        await db.login_attempts.create_index("ip")
        # blocked_ips + notifications for auto-block feature
        await db.blocked_ips.create_index("ip", unique=True)
        await db.blocked_ips.create_index("expires_at")
        await db.security_notifications.create_index("created_at")
        # ---- Hot-path compound indexes (Phase-1 performance) -----------
        # Client dashboard: services/invoices/orders scoped to a user
        await db.services.create_index([("user_id", 1), ("status", 1)])
        await db.orders.create_index([("user_id", 1), ("created_at", -1)])
        await db.invoices.create_index([("user_id", 1), ("status", 1)])
        await db.invoices.create_index([("status", 1), ("due_date", 1)])
        # Renewal automation: duplicate-generation guard lookup + service scoping
        await db.invoices.create_index([("service_id", 1), ("renewal_period", 1)])
        # Global settings: key-value store (billing defaults, feature flags)
        await db.settings.create_index("key", unique=True)
        # Renewal sweep scan: active services approaching next_renewal
        await db.services.create_index([("status", 1), ("next_renewal", 1)])
        await db.tickets.create_index([("user_id", 1), ("status", 1)])
        await db.tickets.create_index([("status", 1), ("updated_at", -1)])
        # MikroTik devices: ordered listing + fast name lookup
        await db.mikrotik_devices.create_index("created_at")
        await db.mikrotik_devices.create_index("name")
        # Admin dashboard: Pusat Notifikasi (device down) + Tagihan Terbaru
        await db.noc_device_state.create_index("status")
        await db.invoices.create_index([("created_at", -1)])
        # Hosting provisioning: lookup akun hosting per kategori + domain
        await db.services.create_index([("category", 1), ("config.domain", 1)])
        # Articles: public listing sorted by publish date, unique slug already set
        await db.articles.create_index([("published", 1), ("published_at", -1)])
        # Assets: filter by category + status combo
        await db.assets.create_index([("category", 1), ("status", 1)])
        # Domains: listing per user, unique nama domain, sweep pengingat expiry
        await db.domains.create_index([("user_id", 1), ("status", 1)])
        await db.domains.create_index("domain", unique=True)
        await db.domains.create_index([("status", 1), ("expires_at", 1)])
        # Leads: listing terbaru + dedupe per email
        await db.leads.create_index([("created_at", -1)])
        await db.leads.create_index("email")
        # NOC DDoS: rules, insiden, log blackhole, saluran notifikasi
        await db.ddos_threshold_rules.create_index("enabled")
        await db.ddos_incidents.create_index([("status", 1), ("started_at", -1)])
        await db.ddos_incidents.create_index([("started_at", -1)])
        await db.blackhole_log.create_index([("at", -1)])
        await db.blackhole_log.create_index("prefix")
        await db.notif_channels.create_index("enabled")
        # Email queue / templates
        await db.email_queue.create_index([("status", 1), ("scheduled_at", 1)])
        # Audit logs: list newest-first + filter by actor
        await db.audit_logs.create_index([("created_at", -1)])
        await db.audit_logs.create_index([("actor_id", 1), ("created_at", -1)])
        # Credit notes: unique numbering + per-invoice lookup
        await db.credit_notes.create_index("number", unique=True)
        await db.credit_notes.create_index([("invoice_id", 1)])
        # NOC: probe samples, transition events, current device state
        await db.noc_probes.create_index([("device_id", 1), ("created_at", -1)])
        await db.noc_probes.create_index([("device_id", 1), ("at", -1)])
        await db.noc_events.create_index([("created_at", -1)])
        await db.noc_events.create_index([("device_id", 1), ("created_at", -1)])
        await db.noc_device_state.create_index("device_id", unique=True)
        # NOC daily uptime rollups (retention job)
        await db.noc_daily_uptime.create_index([("device_id", 1), ("date", 1)], unique=True)
        # Media library
        await db.media_assets.create_index([("tags", 1)])
        # Content calendar
        await db.content_calendar.create_index([("scheduled_at", 1)])
        # Seed atomic number counters from existing data so concurrent
        # first-writes can never collide with legacy numbers.
        for coll, prefix in (("invoices", "INV"), ("tickets", "TCK"),
                              ("quotations", "QTN"), ("credit_notes", "CN")):
            last = await db[coll].find_one({"number": {"$regex": f"^{prefix}-"}},
                                           sort=[("number", -1)])
            if last:
                try:
                    legacy = int(str(last.get("number", "")).rsplit("-", 1)[-1])
                except (TypeError, ValueError):
                    legacy = await db[coll].count_documents({})
                await db.counters.update_one(
                    {"_id": f"number:{coll}"},
                    {"$max": {"seq": legacy}}, upsert=True)
    except Exception as e:
        logger.warning(f"Index create issue: {e}")
    try:
        from portal.seed import seed_all
        await seed_all(db)
        logger.info("Portal seed complete (users, products, sample data).")
    except Exception as e:
        logger.exception(f"Portal seed failed: {e}")
    # At-rest encryption: migrate any legacy plaintext integration secrets.
    try:
        from portal import secretbox
        changed = await secretbox.migrate_at_rest(db)
        if any(changed.values()):
            logger.info(f"Secret at-rest migration encrypted: {changed}")
    except Exception as e:
        logger.exception(f"Secret at-rest migration failed: {e}")
    # Email engine: seed default templates + start invoice-reminder scheduler.
    try:
        from portal import emails as _emails
        await _emails.seed_default_templates(db)
        _emails.start_scheduler(db)
        logger.info("Email engine started (templates seeded, hourly scheduler live).")
    except Exception as e:
        logger.exception(f"Email engine startup failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        from portal import emails as _emails
        _emails.stop_scheduler()
    except Exception:
        pass
    client.close()
