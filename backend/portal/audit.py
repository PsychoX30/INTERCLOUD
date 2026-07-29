"""Audit log helper for sensitive admin actions.

Every write to `audit_logs` is best-effort - a logging failure MUST never
prevent the underlying action from completing (imagine a factory-reset
succeeding but the log-insert exploding: the operator would be locked
out with no evidence of what happened). All callers use fire-and-forget
patterns and swallow exceptions.

Schema (audit_logs collection):
    {
      _id:            ObjectId,
      actor_id:       ObjectId | None,        # None for system/webhook actions
      actor_email:    str,
      actor_role:     str,
      action:         str,                    # e.g., "user.role_change", "billing.settings_update"
      category:       str,                    # security | billing | integrations | users | system | noc
      target_type:    str,                    # e.g., "user", "invoice", "credit_note", "integration"
      target_id:      str | None,             # stringified id of the affected resource
      target_label:   str,                    # human-readable ("john@ex.com", "INV-2026-00001")
      before:         dict | None,            # snapshot before change (redacted secrets)
      after:          dict | None,            # snapshot after change (redacted secrets)
      metadata:       dict,                   # freeform (ip, user_agent, reason, ...)
      ip:             str | None,
      user_agent:     str | None,
      severity:       "info" | "warning" | "critical",
      created_at:     ISO str,
    }
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId

log = logging.getLogger("portal.audit")


# Values considered secret-ish that we redact from before/after snapshots
_SECRET_KEYS = {
    "password", "password_hash", "api_key", "apikey", "api_token", "token",
    "secret", "secret_key", "client_secret", "webhook_secret", "signing_secret",
    "smtp_password", "imap_password", "private_key", "bot_token", "duitku_api_key",
    "merchant_key", "callback_secret",
}


def _redact(value: Any) -> Any:
    """Recursively replace secret-ish fields with '••••'."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k.lower() in _SECRET_KEYS and v not in (None, "", []):
                out[k] = "••••"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(x) for x in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _actor_from(caller: dict | None) -> tuple[Optional[ObjectId], str, str]:
    if not caller:
        return None, "system", "system"
    aid = caller.get("id") or caller.get("_id")
    try:
        oid = ObjectId(aid) if aid and not isinstance(aid, ObjectId) else aid
    except Exception:
        oid = None
    return oid, str(caller.get("email") or "system"), str(caller.get("role") or "system")


def _extract_request(request) -> tuple[Optional[str], Optional[str]]:
    if not request:
        return None, None
    try:
        ip = request.client.host if request.client else None
    except Exception:
        ip = None
    try:
        ua = request.headers.get("user-agent") if hasattr(request, "headers") else None
    except Exception:
        ua = None
    return ip, ua


async def log_audit(
    db,
    *,
    actor: dict | None,
    action: str,
    category: str = "system",
    target_type: str = "",
    target_id: str | None = None,
    target_label: str = "",
    before: dict | None = None,
    after: dict | None = None,
    metadata: dict | None = None,
    severity: str = "info",
    request=None,
) -> None:
    """Insert a single audit_logs row. Never raises - best-effort only."""
    try:
        actor_id, actor_email, actor_role = _actor_from(actor)
        ip, ua = _extract_request(request)
        doc = {
            "actor_id": actor_id,
            "actor_email": actor_email,
            "actor_role": actor_role,
            "action": action,
            "category": category,
            "target_type": target_type,
            "target_id": str(target_id) if target_id is not None else None,
            "target_label": target_label,
            "before": _redact(before) if before is not None else None,
            "after": _redact(after) if after is not None else None,
            "metadata": _redact(metadata or {}),
            "ip": ip,
            "user_agent": ua,
            "severity": severity,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.audit_logs.insert_one(doc)
    except Exception as e:  # noqa: BLE001
        log.warning(f"audit log insert failed for action={action}: {e}")


def serialize(doc: dict) -> dict:
    """Convert a raw Mongo audit_logs doc → JSON-safe dict for the API."""
    return {
        "id": str(doc.get("_id")),
        "actor_id": str(doc["actor_id"]) if doc.get("actor_id") else None,
        "actor_email": doc.get("actor_email", ""),
        "actor_role": doc.get("actor_role", ""),
        "action": doc.get("action", ""),
        "category": doc.get("category", "system"),
        "target_type": doc.get("target_type", ""),
        "target_id": doc.get("target_id"),
        "target_label": doc.get("target_label", ""),
        "before": doc.get("before"),
        "after": doc.get("after"),
        "metadata": doc.get("metadata", {}),
        "ip": doc.get("ip"),
        "user_agent": doc.get("user_agent"),
        "severity": doc.get("severity", "info"),
        "created_at": doc.get("created_at", ""),
    }
