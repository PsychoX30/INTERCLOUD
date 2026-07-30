"""First-boot seed - creates ONLY the admin user.

On a fresh install we want the operator to start from an empty slate so the
system is immediately usable for real customers, without demo debris to
clean up. Historic demo seeding (client, sales/support/ticket-agent users,
sample products, invoices, tickets, articles) has been removed - those
records will only exist if the operator (or a restored backup) creates
them.

The seeder still runs on every boot but is fully idempotent: the admin is
created once and, if the ADMIN_PASSWORD env var later changes, the stored
hash is re-synced so the operator can always log in with whatever is in
`backend/.env`.

Legacy asset-schema migration is preserved because it is data-safe and
touches existing prod data on the update path.
"""
import os
from datetime import datetime, timezone

from .auth import hash_password, verify_password


async def seed_all(db):
    await _seed_admin(db)
    await _migrate_assets_straight_line(db)
    await _write_credentials_file(db)


async def _seed_admin(db):
    """Create the admin user on first boot; re-sync the password hash if
    ADMIN_PASSWORD later changes in backend/.env.

    Production safety: the well-known dev default password is ONLY used in
    the development environment (detected via /app/memory). On a production
    box without ADMIN_PASSWORD set, a random password is generated and
    logged ONCE with a must-change flag."""
    admin_email = os.environ.get("ADMIN_EMAIL", "support@intercloud-digital.com").lower()
    admin_pw    = os.environ.get("ADMIN_PASSWORD")
    is_dev      = os.path.isdir("/app/memory")

    a = await db.users.find_one({"email": admin_email})
    if not a:
        generated = False
        if not admin_pw:
            if is_dev:
                admin_pw = "AdminIntercloud2026!"
            else:
                import secrets as _secrets
                admin_pw = _secrets.token_urlsafe(18)
                generated = True
        must_change = generated or os.environ.get(
            "ADMIN_MUST_CHANGE_PASSWORD", "").lower() in ("1", "true", "yes")
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_pw),
            "name": "Administrator",
            "role": "admin",
            "company": "",
            "phone": "",
            "assigned_client_ids": [],
            "billing_emails": [],
            "must_change_password": must_change,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        if generated:
            import logging
            logging.getLogger(__name__).warning(
                "[seed] ADMIN_PASSWORD was not set - generated a one-time random "
                "admin password for %s: %s  (login and change it immediately)",
                admin_email, admin_pw)
    elif admin_pw and not verify_password(admin_pw, a["password_hash"]):
        # Env-driven password rotation - keeps the door open for the operator
        # who edits backend/.env to change the admin password.
        await db.users.update_one(
            {"_id": a["_id"]},
            {"$set": {"password_hash": hash_password(admin_pw)}},
        )


async def _migrate_assets_straight_line(db):
    """One-shot backfill: ensure every asset doc has `salvage_value` and
    `useful_life_years` fields so the straight-line depreciation formula
    can be applied without falling back to legacy heuristics on every read.

    Safe on empty DBs (does nothing) and safe to run repeatedly.
    """
    updated = 0
    async for a in db.assets.find({}):
        patch = {}
        if "salvage_value" not in a:
            patch["salvage_value"] = 0.0
        if not int(a.get("useful_life_years", 0) or 0):
            life_m = int(a.get("useful_life_months", 0) or 0)
            dep_pct = float(a.get("depreciation_percent", 0) or 0)
            if life_m > 0:
                patch["useful_life_years"] = max(1, round(life_m / 12))
            elif dep_pct > 0:
                patch["useful_life_years"] = max(1, round(100.0 / dep_pct))
        if patch:
            await db.assets.update_one({"_id": a["_id"]}, {"$set": patch})
            updated += 1
    if updated:
        import logging
        logging.getLogger(__name__).info(
            "[assets] straight-line migration backfilled %d asset(s)", updated
        )


async def _write_credentials_file(db):
    """Write the admin credentials to /app/memory/test_credentials.md for the
    dev/test harness ONLY. Skipped entirely in production installs (the
    /app/memory folder only exists in the development environment), so no
    plaintext credentials ever land on a production server."""
    admin_email = os.environ.get("ADMIN_EMAIL", "support@intercloud-digital.com")
    admin_pw    = os.environ.get("ADMIN_PASSWORD", "AdminIntercloud2026!")
    path = "/app/memory/test_credentials.md"
    try:
        if not os.path.isdir("/app/memory"):
            return
        with open(path, "w") as f:
            f.write("# Intercloud Portal - First-boot credentials\n\n")
            f.write("The installer seeds ONE user (admin). All other data starts empty.\n\n")
            f.write(f"| Role  | Email | Password |\n| --- | --- | --- |\n")
            f.write(f"| admin | {admin_email} | {admin_pw} |\n\n")
            f.write("Change the password immediately after first login via "
                    "Portal ▸ Settings ▸ Change Password.\n")
    except Exception:
        pass
