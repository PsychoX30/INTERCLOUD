"""JWT + bcrypt auth for the Intercloud client portal.

Roles:
- admin       : full access (superuser)
- owner       : read-only globally (executive visibility - MRR/ARPU/churn/uptime)
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
ACCESS_TOKEN_TTL_MINUTES = 120  # 2 hours; see session versioning below.

STAFF_ROLES = {"admin", "owner", "sales", "finance", "support", "ticket_only", "creative"}
FINANCE_ROLES = {"admin", "owner", "finance"}  # sees revenue/finance widgets (owner read-only)
BILLING_ROLES = {"admin", "sales"}  # invoices/quotations
CATALOG_ROLES = {"admin", "support"}  # product mgmt
OPS_ROLES = {"admin", "support"}  # provisioning/mikrotik/dcim/diagnostics
USER_MGMT_ROLES = {"admin"}
# Landing CMS: the admin UI exposes the 146-slot editor to every staff role, but
# only these roles may publish. Kept as a set so the route dependency and the UI
# guard read the same source of truth - a literal `role != "admin"` in a route
# silently gives a working-looking page that 403s on save.
SITE_CONTENT_ROLES = {"admin"}
TICKET_ROLES = {"admin", "sales", "support", "ticket_only"}
# Executive read-only visibility - cannot write, only see aggregated dashboards.
OWNER_ROLES = {"admin", "owner"}
# Digital Creative team - read/write scoped to content tooling ONLY
# (articles, media library, content calendar). No billing/CRM/NOC/finance.
CONTENT_ROLES = {"admin", "creative"}


def _secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str,
                        *, sv: int = 0) -> str:
    """Mint a portal access token.

    `sv` is the user's `session_version` baked into the token. `_resolve_user`
    rejects any token whose `sv` no longer matches the stored value, so
    rotating a token is just an `$inc: {session_version: 1}` on the user row.

    Before this existed a stolen token stayed valid for its full lifetime
    (7 days) with no way to revoke it — password change, admin reset, and
    "log out everywhere" all left it working. Tokens are now 2 hours and
    revocable.
    """
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "sv": int(sv),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])


SHARE_TOKEN_TTL_MINUTES = 30


def create_share_token(token_hash: str) -> str:
    """Short-lived JWT proving a password-protected share link was unlocked.

    NOT a user access token: subject is not a user id and role is absent, so
    get_current_user/get_current_staff will always reject it. Only the public
    share endpoints (which validate share_token_hash against the path token)
    accept it.
    """
    payload = {
        "sub": "share-link",
        "scope": "share-link",
        "share_token_hash": token_hash,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=SHARE_TOKEN_TTL_MINUTES),
        "type": "share",
    }
    return jwt.encode(payload, _secret(), algorithm=JWT_ALGORITHM)


def decode_share_token(token: str) -> dict:
    data = jwt.decode(token, _secret(), algorithms=[JWT_ALGORITHM])
    if data.get("type") != "share" or data.get("scope") != "share-link":
        raise jwt.InvalidTokenError("not a share-link token")
    return data


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
    # Revoke in-flight access the moment an account is deactivated: without
    # this, an already-issued token keeps working until it expires (7 days),
    # so toggling a user off would not actually cut them off.
    if user.get("is_active") is False:
        raise HTTPException(status_code=401, detail="Akun dinonaktifkan")
    # Revoke every previously-issued token for this account. The token carries
    # the `sv` it was minted with; bumping session_version on the user row
    # (password change/reset, admin action, "log out everywhere") invalidates
    # all of them at once. Tokens minted before this field existed have no
    # `sv` and are treated as 0, which matches the absent-field default, so
    # the change does not log anybody out on deploy.
    if int(payload.get("sv") or 0) != int(user.get("session_version") or 0):
        raise HTTPException(status_code=401, detail="Sesi berakhir, silakan login ulang")
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


async def get_current_content(user=Depends(get_current_user)):
    """Content tooling (articles/media/calendar): admin + creative."""
    if user.get("role") not in CONTENT_ROLES:
        raise HTTPException(status_code=403, detail="Content team only")
    return user


# Roles allowed to author KB (knowledge-base) articles.
# Broader than CONTENT_ROLES: support staff can write KB articles to help clients,
# but cannot publish blog/marketing articles or manage media/calendar.
KB_AUTHOR_ROLES = {"admin", "creative", "support"}


async def get_current_kb_author(user=Depends(get_current_user)):
    """KB article authoring: admin + creative + support."""
    if user.get("role") not in KB_AUTHOR_ROLES:
        raise HTTPException(status_code=403, detail="KB authoring not allowed for your role")
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


async def get_current_site_content_editor(user=Depends(get_current_user)):
    """Landing CMS publish rights.

    Reads `SITE_CONTENT_ROLES` rather than hard-coding `role != "admin"`. The
    message names the requirement so a staff member who reaches the editor UI
    (the page itself is not role-gated on the client) understands why saving
    is refused instead of seeing a bare "Admin only".
    """
    if user.get("role") not in SITE_CONTENT_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Landing CMS is read-only for your role; only an admin can publish changes",
        )
    return user


def sales_can_access(user: dict, client_user_id: str) -> bool:
    """Sales role must have the client in assigned_client_ids."""
    if user.get("role") != "sales":
        return True
    assigned = user.get("assigned_client_ids") or []
    return str(client_user_id) in [str(x) for x in assigned]


# ---------------------------------------------------------------------------
# Per-user feature flags
# ---------------------------------------------------------------------------
# A flag is a capability that is NOT implied by the role. Roles get a default
# set; a user may be customised (`feature_flags_custom = True`) so that flags can
# be granted AND revoked individually. Admin always passes (see require_flag),
# so tightening or extending this table can never lock the console out.
ALL_FEATURE_FLAGS = (
    "can_delete_invoices", "can_delete_users", "can_delete_tickets",
    "can_run_factory_reset", "can_view_all_invoices", "can_edit_pricing",
    "can_apply_discounts", "can_view_assets", "can_export_data",
    "can_edit_dcim_devices", "can_edit_ip_prefixes", "can_run_provisioning",
    "can_control_mikrotik", "can_run_diagnostics", "can_manage_users",
    "can_manage_articles", "can_edit_branding", "can_manage_integrations",
    "can_manage_projects", "can_manage_content", "can_manage_crm",
    "can_manage_followups", "can_manage_forms",
    "can_run_backups", "can_delete_backups", "can_view_all_clients",
    "can_reassign_clients", "can_impersonate_client",
    "can_view_email_automation", "can_manage_tickets", "can_manage_sla",
)

# Defaults mirror what each role can already do, so enabling enforcement does
# not take anything away. `ticket_only` and `creative` intentionally get none.
ROLE_DEFAULT_FLAGS = {
    "admin": set(ALL_FEATURE_FLAGS),
    "owner": {"can_view_all_invoices", "can_view_assets", "can_view_all_clients"},
    # `can_manage_sla` is deliberately absent: SLA incident writes are
    # admin/support today, so granting the flag by default would widen access.
    # It stays available for an ad-hoc grant instead.
    "finance": {"can_view_all_invoices", "can_view_assets", "can_export_data",
                "can_edit_pricing", "can_apply_discounts",
                "can_manage_tickets",
                "can_manage_crm", "can_manage_followups",
                "can_manage_content"},
    "sales": {"can_export_data", "can_apply_discounts",
              "can_manage_tickets", "can_view_all_clients",
              "can_manage_projects", "can_manage_crm", "can_manage_followups",
              "can_manage_content", "can_manage_forms"},
    "support": {"can_edit_dcim_devices", "can_edit_ip_prefixes",
                "can_run_provisioning", "can_control_mikrotik",
                "can_run_diagnostics", "can_manage_sla", "can_manage_tickets",
                "can_manage_articles", "can_manage_projects",
                "can_manage_crm", "can_manage_followups", "can_manage_content"},
    "ticket_only": {"can_manage_tickets"},
    "creative": {"can_manage_articles", "can_manage_content", "can_manage_forms"},
}


def effective_flags(user: dict) -> set:
    """Flags in force for this user.

    When the account has never been customised, the role defaults apply — the
    same capabilities the role already had. Once customised, the stored list is
    authoritative, which is what makes a flag removable as well as grantable.
    """
    if user.get("feature_flags_custom"):
        return set(user.get("feature_flags") or [])
    role = user.get("role") or ""
    return set(ROLE_DEFAULT_FLAGS.get(role, set()))


def has_flag(user: dict, key: str) -> bool:
    if (user.get("role") or "") == "admin":
        return True
    return key in effective_flags(user)


def _menu_default_roles(keys: tuple) -> set:
    """Role defaults for a menu, read from the catalog the UI itself renders.

    Imported lazily: `routes.users` imports from this module, so a module-level
    import would be circular. Routing the defaults through the catalog instead of
    a second hard-coded table is what keeps "what the modal shows as default" and
    "what the server allows without an allow-list" from drifting apart.
    """
    from .routes.users import ADMIN_MENU_CATALOG  # local import: avoids a cycle

    out: set = set()
    for m in ADMIN_MENU_CATALOG:
        if m.get("key") in keys:
            out |= set(m.get("default_roles") or [])
    return out


# A merged console is one sidebar entry fronting several former menus. Granting
# the umbrella must reach every panel inside it; granting one panel key must NOT
# reach the others (that key is already checked as a `wanted` key of its own
# surface). Kept as a one-tuple so no endpoint can widen access by accident.
CONSOLE_GRANT = ("operations_center",)


def require_menu(*keys: str, grant_via: tuple = ()):
    """Dependency: caller may read this menu surface.

    The same rule the sidebar uses, enforced on the server:

    * an explicit `menu_keys` allow-list is authoritative in BOTH directions —
      granting a menu the role would not normally have works, and a menu missing
      from the list is refused even for a role that has it by default;
    * with no allow-list, the catalog's `default_roles` decide.

    This exists because a menu that renders but whose API answers 403 is worse
    than a menu that is hidden: the operator grants access, the page opens, and
    the panel sits empty with no explanation. `menu_keys` was already being read
    by the frontend, so a read surface had to honour it too.

    Multiple keys are accepted so an endpoint shared by two pages (the device
    list behind both MikroTik Ops and Services, for example) stays reachable
    through either grant.

    Read-only by intent. Write routes stay behind `require_flag`, which keeps
    "can you see this" and "can you change this" separate: a sales user can be
    given the MikroTik panel to look at without gaining the ability to reboot a
    router.
    """
    wanted = tuple(keys)
    # `grant_via` names menu keys that only an explicit allow-list may use to
    # reach this surface. It exists for the merged consoles: Operations Center
    # is one sidebar entry fronting seven former menus, and an operator who
    # grants "operations_center" must reach the panels inside it. Leaving those
    # keys out of `wanted` keeps the role defaults untouched, so a role that
    # could not read NOC before still cannot read it merely because the console
    # merged its tabs together.
    granted = tuple(grant_via)
    defaults = _menu_default_roles(wanted)

    async def _dep(user=Depends(get_current_staff)):
        role = user.get("role") or ""
        if role == "admin":
            return user
        allow = user.get("menu_keys") or []
        if allow:
            if any(k in allow for k in wanted) or any(k in allow for k in granted):
                return user
            raise HTTPException(
                status_code=403,
                detail=(
                    "Menu ini belum diaktifkan untuk akun Anda. "
                    "Minta admin menambahkannya di Users -> Manage access."
                ),
            )
        if role in defaults:
            return user
        raise HTTPException(
            status_code=403,
            detail=f"Menu ini hanya untuk role: {', '.join(sorted(defaults)) or 'admin'}",
        )

    return _dep


def require_flag(*keys: str):
    """Dependency: caller must hold at least one of `keys` (admin always passes).

    Built on `get_current_staff`, so a client token can never satisfy it even if
    a flag is somehow set on a client account. Admin bypasses the flag check but
    still has to be staff, which keep the two gates independent: role decides
    which surface you can reach, the flag decides whether an optional capability
    is switched on for you.
    """
    wanted = tuple(keys)

    async def _dep(user=Depends(get_current_staff)):
        if (user.get("role") or "") == "admin":
            return user
        granted = effective_flags(user)
        if not any(k in granted for k in wanted):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Fitur ini belum diaktifkan untuk akun Anda "
                    f"({', '.join(wanted)}). Minta admin mengaktifkannya di "
                    "Users -> Manage access."
                ),
            )
        return user

    return _dep
