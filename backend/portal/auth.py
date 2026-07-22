"""JWT + bcrypt auth for the Intercloud client portal.

Roles:
- admin       : full access (superuser)
- sales       : limited to their assigned clients; can create quotes/orders for them
- support     : product + tech tools + all tickets; CANNOT see finance/revenue
- ticket_only : only tickets (read + reply)
- client      : end-user portal
"""
import os
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = 60 * 24 * 7  # 1 week for portal use

STAFF_ROLES = {"admin", "sales", "support", "ticket_only"}
FINANCE_ROLES = {"admin"}  # only admin sees revenue/finance
BILLING_ROLES = {"admin", "sales"}  # invoices/quotations
CATALOG_ROLES = {"admin", "support"}  # product mgmt
OPS_ROLES = {"admin", "support"}  # provisioning/mikrotik/dcim/diagnostics
USER_MGMT_ROLES = {"admin"}
TICKET_ROLES = {"admin", "sales", "support", "ticket_only"}


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])


bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_user(request: Request, creds: HTTPAuthorizationCredentials | None):
    from server import db  # local import avoids circular
    token = None
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    if not token:
        # Support ?token=... for links opened in a new tab (PDF previews)
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    try:
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token subject")
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    user["id"] = str(user.pop("_id"))
    user.pop("password_hash", None)
    # Normalize assigned_client_ids to str list
    if "assigned_client_ids" in user:
        user["assigned_client_ids"] = [str(x) for x in (user["assigned_client_ids"] or [])]
    if "billing_emails" in user:
        user["billing_emails"] = list(user["billing_emails"] or [])
    # Attach the raw token so downstream endpoints (e.g., PDF page)
    # can generate self-links that include the token as a query param.
    user["_token"] = token
    return user


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    return await _resolve_user(request, creds)


async def get_current_staff(user=Depends(get_current_user)):
    """Any staff role (admin/sales/support/ticket_only)."""
    if user.get("role") not in STAFF_ROLES:
        raise HTTPException(status_code=403, detail="Staff only")
    return user


async def get_current_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_roles(*allowed):
    """Factory: dependency that only allows the listed roles."""
    allowed_set = set(allowed)

    async def _dep(user=Depends(get_current_user)):
        if user.get("role") not in allowed_set:
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {', '.join(sorted(allowed_set))}",
            )
        return user

    return _dep


def sales_can_access(user: dict, client_user_id: str) -> bool:
    """Sales role must have the client in assigned_client_ids."""
    if user.get("role") != "sales":
        return True
    assigned = user.get("assigned_client_ids") or []
    return str(client_user_id) in [str(x) for x in assigned]
