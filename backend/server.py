from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List
import uuid
from datetime import datetime, timezone


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

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


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup_seed():
    try:
        await db.users.create_index("email", unique=True)
        await db.invoices.create_index("number", unique=True)
        await db.tickets.create_index("number", unique=True)
        await db.quotations.create_index("number", unique=True)
    except Exception as e:
        logger.warning(f"Index create issue: {e}")
    try:
        from portal.seed import seed_all
        await seed_all(db)
        logger.info("Portal seed complete (users, products, sample data).")
    except Exception as e:
        logger.exception(f"Portal seed failed: {e}")
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
