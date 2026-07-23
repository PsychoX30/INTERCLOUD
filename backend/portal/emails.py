"""Automated email/notification engine for the Intercloud portal.

Three tiers of trigger:

  * INSTANT — fired synchronously (best-effort) from event hooks in routes.py:
      welcome, order_confirmation, invoice_generated, password_reset

  * SCHEDULED — fired by an APScheduler cron job that runs every hour and
    scans unpaid invoices, matching them to templates keyed by their
    `offset_days` value relative to `due_date`:
      -3  → invoice_reminder_d3
       0  → invoice_due
      +1  → invoice_overdue_d1
      +3  → invoice_overdue_d3
      +7  → invoice_overdue_d7
      +8  → service_suspension  (also flips linked services to `suspended`)

  * ON-DEMAND — admin explicitly triggers a blast:
      maintenance, newsletter

Every send is written to `email_logs` with an audit trail (status,
error, delivered_via). If the SMTP integration isn't configured, sends
are logged with status=`skipped` and delivered_via=`log` so nothing
crashes and the admin can see why nothing arrived.
"""

from __future__ import annotations
import logging
import os
import re
import string
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from bson import ObjectId

from . import integrations_v2 as iv2

log = logging.getLogger("portal.emails")


# ============================================================
# Default template library — seeded on first startup
# ============================================================
# HTML wrapper applied to every rendered body so newsletters and
# transactional mail share consistent branding.
BRAND_HEADER = "#0a2350"
BRAND_ACCENT = "#f5b120"
LOGO_URL = "https://customer-assets-lxgj4vgw.emergentagent.net/job_portal-straight-line/artifacts/40f397oz_logo_anang-02-1-1536x1536-1.png"

_WRAPPER = """<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f6fb;font-family:'Segoe UI',-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif;color:#0a2350">
  <div style="max-width:640px;margin:24px auto;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 6px 28px rgba(10,35,80,.08);border:1px solid #e2e8f0">
    <div style="background:#0a2350;padding:22px 28px;color:#fff">
      <img src="__LOGO__" alt="PT Intercloud Digital Inovasi" style="height:36px;width:auto;display:block" />
    </div>
    <div style="padding:32px 28px;font-size:14px;line-height:1.7;color:#0f172a">
      {body}
    </div>
    <div style="background:#f8fafc;padding:18px 28px;font-size:11px;color:#64748b;border-top:1px solid #e2e8f0;line-height:1.6">
      <div style="font-weight:700;color:#0a2350;letter-spacing:.02em">PT Intercloud Digital Inovasi</div>
      Cyber 1 Building, Kuningan · Jakarta 12950, Indonesia<br>
      <a href="https://intercloud-digital.com" style="color:#0a2350;text-decoration:none">intercloud-digital.com</a>
      &nbsp;·&nbsp;
      <a href="mailto:support@intercloud-digital.com" style="color:#0a2350;text-decoration:none">support@intercloud-digital.com</a>
      &nbsp;·&nbsp; WhatsApp <a href="https://wa.me/6287812397187" style="color:#0a2350;text-decoration:none">+62 878-1239-7187</a>
      <div style="margin-top:8px;color:#94a3b8;font-size:10px">This is an automated message from the Intercloud Client Portal. Please do not reply directly — use the portal or contact channels above.</div>
    </div>
  </div>
</body></html>""".replace("__LOGO__", LOGO_URL)


# Bump this whenever the shipped default templates meaningfully change — startup
# will then refresh any unedited system templates in place.
_SEED_VERSION = 2


DEFAULT_TEMPLATES: list[dict] = [
    {
        "event_key": "welcome",
        "name": "Welcome — new user registration",
        "subject": "Welcome to Intercloud, {{user.name}} — your portal is ready",
        "body_html": (
            "<p style='font-size:15px'>Dear <b>{{user.name}}</b>,</p>"
            "<p>Thank you for choosing <b>PT Intercloud Digital Inovasi</b>. Your Client Portal account has been activated and is ready to use.</p>"
            "<p>From your portal you can:</p>"
            "<ul style='padding-left:20px;margin:8px 0 16px'>"
            "  <li>Order Cloud, VPS, Hosting, Colocation, Dedicated Server, and connectivity services</li>"
            "  <li>Track invoices, download PDF receipts, and pay online</li>"
            "  <li>Open technical or billing support tickets 24/7</li>"
            "  <li>Monitor bandwidth, uptime, and service health</li>"
            "</ul>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.login_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;letter-spacing:.02em'>Open Client Portal &rarr;</a>"
            "</p>"
            "<p>Should you require any assistance getting started, our team is available around the clock at "
            "<a href='mailto:support@intercloud-digital.com'>support@intercloud-digital.com</a> "
            "or via WhatsApp at +62 878-1239-7187.</p>"
            "<p style='margin-top:24px'>Warm regards,<br><b>The Intercloud Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "order_confirmation",
        "name": "Order confirmation — instant",
        "subject": "Order received — {{order.product_name}} (Ref #{{order.id_short}})",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Thank you for your order. We have successfully received your request and it is now being processed by our team.</p>"
            "<table style='width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:10px;overflow:hidden'>"
            "  <tr><td style='padding:10px 14px;color:#64748b;font-size:12px;width:40%'>Reference</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>#{{order.id_short}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Service</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{order.product_name}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Current status</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{order.status}}</td></tr>"
            "</table>"
            "<p>An invoice has been issued and is available in your portal. Once payment is verified, provisioning will commence automatically.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.login_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>View &amp; pay invoice &rarr;</a>"
            "</p>"
            "<p>If you have any questions or wish to modify your order, please reply to this thread or contact our sales team at "
            "<a href='mailto:sales@intercloud-digital.com'>sales@intercloud-digital.com</a>.</p>"
            "<p style='margin-top:24px'>Kind regards,<br><b>Intercloud Sales Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_generated",
        "name": "Invoice issued — instant (D-14 baseline)",
        "subject": "Invoice {{invoice.number}} — {{invoice.total_fmt}} (due {{invoice.due_date}})",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>A new invoice has been issued to your account. Kindly review the details below at your convenience.</p>"
            "<table style='width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:10px;overflow:hidden'>"
            "  <tr><td style='padding:10px 14px;color:#64748b;font-size:12px;width:40%'>Invoice number</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{invoice.number}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Amount due</td><td style='padding:10px 14px;font-weight:700;color:#0a2350;font-size:16px'>{{invoice.total_fmt}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Due date</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{invoice.due_date}}</td></tr>"
            "</table>"
            "<p>You may pay directly from your portal via bank transfer or online gateway.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Open invoice &rarr;</a>"
            "</p>"
            "<p style='color:#64748b;font-size:12px'>Bank transfer details (IDR):<br>"
            " · Mandiri &mdash; 1240011911816 (a.n. PT Intercloud Digital Inovasi)<br>"
            " · BCA &mdash; 4730862038 (a.n. PT Intercloud Digital Inovasi)</p>"
            "<p>Should you have any billing questions, please contact "
            "<a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a>. Thank you for your continued business.</p>"
            "<p style='margin-top:24px'>Sincerely,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_reminder_d3",
        "name": "Payment reminder — 3 days before due",
        "subject": "Friendly reminder: invoice {{invoice.number}} due in 3 days",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>We hope this message finds you well. This is a friendly reminder that invoice "
            "<b>{{invoice.number}}</b> in the amount of <b>{{invoice.total_fmt}}</b> "
            "will be due on <b>{{invoice.due_date}}</b> (in 3 days).</p>"
            "<p>To avoid any interruption to your services, please arrange payment at your earliest convenience.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Review &amp; pay invoice &rarr;</a>"
            "</p>"
            "<p>If payment has already been submitted, please disregard this notice — our systems will update within 1&ndash;2 business hours after settlement.</p>"
            "<p style='margin-top:24px'>Kind regards,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": -3,
        "send_time": "08:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_due",
        "name": "Payment due — today",
        "subject": "Invoice {{invoice.number}} is due today",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Invoice <b>{{invoice.number}}</b> in the amount of <b>{{invoice.total_fmt}}</b> is due today, <b>{{invoice.due_date}}</b>.</p>"
            "<p>Kindly proceed with payment to keep your services in good standing. If payment is not received by end of day, the invoice will be marked as overdue and reminders will follow.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Pay now &rarr;</a>"
            "</p>"
            "<p>Should you require an extension or wish to arrange a different payment schedule, our finance team is happy to assist at "
            "<a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a>.</p>"
            "<p style='margin-top:24px'>Thank you,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": 0,
        "send_time": "08:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_overdue_d1",
        "name": "Overdue notice — D+1",
        "subject": "Overdue: invoice {{invoice.number}} (1 day past due)",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Our records indicate that invoice <b>{{invoice.number}}</b> in the amount of "
            "<b>{{invoice.total_fmt}}</b>, originally due on {{invoice.due_date}}, is now <b>1 day past due</b>.</p>"
            "<p>Your services remain active at this time. To avoid future interruption, please arrange payment at your earliest opportunity.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Settle invoice &rarr;</a>"
            "</p>"
            "<p>If you have already made payment or are experiencing difficulty, please contact us at "
            "<a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a> so we may assist promptly.</p>"
            "<p style='margin-top:24px'>Kind regards,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": 1,
        "send_time": "09:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_overdue_d3",
        "name": "Overdue notice — D+3",
        "subject": "Second notice: invoice {{invoice.number}} (3 days past due)",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>This is a follow-up regarding invoice <b>{{invoice.number}}</b> "
            "(<b>{{invoice.total_fmt}}</b>), which remains outstanding <b>3 days past due</b>.</p>"
            "<p>We kindly request that you settle this invoice as soon as possible to prevent any impact on your active services.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Pay outstanding balance &rarr;</a>"
            "</p>"
            "<p>Should there be any concerns or if you require a payment arrangement, please reach out to our finance team at "
            "<a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a>. We are here to help.</p>"
            "<p style='margin-top:24px'>Sincerely,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": 3,
        "send_time": "09:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_overdue_d7",
        "name": "Overdue notice — D+7 (final warning)",
        "subject": "URGENT — invoice {{invoice.number}} 7 days past due · services will be suspended",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Despite our previous reminders, invoice <b>{{invoice.number}}</b> in the amount of "
            "<b>{{invoice.total_fmt}}</b> remains unpaid <b>7 days past its due date</b>.</p>"
            "<p><b>Please note:</b> if payment is not received within the next 24 hours, "
            "your active services will be automatically <b>suspended tomorrow</b> in accordance with our SLA.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#c0392b;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Pay now to avoid suspension &rarr;</a>"
            "</p>"
            "<p>If you are experiencing any difficulty with payment or believe this to be in error, please contact us immediately at "
            "<a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a> "
            "or WhatsApp +62 878-1239-7187 so we may assist.</p>"
            "<p style='margin-top:24px'>Respectfully,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": 7,
        "send_time": "09:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "service_suspension",
        "name": "Service suspension — D+8",
        "subject": "Notice of service suspension — invoice {{invoice.number}}",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>We regret to inform you that, as invoice <b>{{invoice.number}}</b> "
            "(<b>{{invoice.total_fmt}}</b>) has remained unpaid for more than 8 days past its due date, "
            "your active services have been <b>suspended</b> as of today.</p>"
            "<p>Suspended services will be <b>reactivated automatically</b> once payment has been received and verified. "
            "Data and configurations remain intact during suspension.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Settle invoice &amp; restore services &rarr;</a>"
            "</p>"
            "<p>If you believe this suspension to be in error or wish to arrange payment terms, "
            "please contact our finance team without delay at "
            "<a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a> "
            "or WhatsApp +62 878-1239-7187.</p>"
            "<p>We value your business and look forward to restoring service promptly.</p>"
            "<p style='margin-top:24px'>Respectfully,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": 8,
        "send_time": "09:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "password_reset",
        "name": "Password reset request",
        "subject": "Reset your Intercloud portal password",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>We received a request to reset the password associated with your Intercloud Client Portal account. "
            "You may set a new password by clicking the button below. This link will remain valid for the next <b>60 minutes</b>.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{reset_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Reset password &rarr;</a>"
            "</p>"
            "<p style='color:#64748b;font-size:12px'>If the button does not work, please copy and paste the following link into your browser:<br>"
            "<span style='word-break:break-all'>{{reset_url}}</span></p>"
            "<p style='color:#64748b;font-size:12px;margin-top:18px'>If you did not request a password reset, no action is required &mdash; your password will remain unchanged. "
            "For security concerns, contact <a href='mailto:security@intercloud-digital.com'>security@intercloud-digital.com</a> immediately.</p>"
            "<p style='margin-top:24px'>Kind regards,<br><b>Intercloud Security Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "maintenance",
        "name": "Scheduled maintenance notification",
        "subject": "Scheduled maintenance notice — {{maintenance.title}}",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>We would like to inform you that PT Intercloud Digital Inovasi will be conducting scheduled maintenance as detailed below. "
            "This activity is necessary to ensure the continued reliability, security, and performance of our infrastructure.</p>"
            "<table style='width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:10px;overflow:hidden'>"
            "  <tr><td style='padding:10px 14px;color:#64748b;font-size:12px;width:32%'>Activity</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{maintenance.title}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Maintenance window</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{maintenance.window}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Expected impact</td><td style='padding:10px 14px;color:#0f172a'>{{maintenance.impact}}</td></tr>"
            "</table>"
            "<p>Our engineering team will make every effort to minimise disruption during this window. Should you have any questions or require additional information, "
            "please contact our NOC at <a href='mailto:noc@intercloud-digital.com'>noc@intercloud-digital.com</a> or WhatsApp +62 878-1239-7187.</p>"
            "<p>We apologise for any inconvenience and appreciate your patience and understanding.</p>"
            "<p style='margin-top:24px'>Best regards,<br><b>Intercloud NOC Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "newsletter",
        "name": "Newsletter — monthly (default shell)",
        "subject": "Intercloud Insights — {{month.name}}",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Welcome to this month's edition of <b>Intercloud Insights</b> &mdash; our digest of product updates, industry perspectives, and behind-the-scenes stories from PT Intercloud Digital Inovasi.</p>"
            "<p style='color:#64748b;font-size:12px;font-style:italic'>Editor's note: replace this default body with your newsletter content before broadcasting. "
            "You may use variables such as <code>{{user.name}}</code>, <code>{{month.name}}</code>, or any custom content and images.</p>"
            "<h3 style='color:#0a2350;margin-top:24px;font-size:16px'>Highlights this month</h3>"
            "<ul style='padding-left:20px'>"
            "  <li>Product release notes</li>"
            "  <li>Uptime &amp; performance report</li>"
            "  <li>Feature spotlight</li>"
            "  <li>Upcoming events &amp; webinars</li>"
            "</ul>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.login_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Visit your portal &rarr;</a>"
            "</p>"
            "<p>Thank you for being part of the Intercloud community. We appreciate your continued trust in our services.</p>"
            "<p style='margin-top:24px'>Warm regards,<br><b>The Intercloud Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
]


async def seed_default_templates(db) -> None:
    """Insert missing system templates. Refresh existing ones when the code-side
    version bumps (so shipping improved defaults is a code change, not a manual
    DB migration). We do NOT clobber templates whose `send_count > 0` — those
    are already in production use and may have been intentionally edited.
    """
    now = datetime.now(timezone.utc).isoformat()
    for tpl in DEFAULT_TEMPLATES:
        existing = await db.email_templates.find_one({"event_key": tpl["event_key"]})
        if not existing:
            doc = {**tpl, "_seed_version": _SEED_VERSION,
                   "created_at": now, "updated_at": now,
                   "last_sent_at": None, "send_count": 0}
            await db.email_templates.insert_one(doc)
            continue
        # Refresh subject/body/is_system/name only when we've shipped a newer
        # canonical version AND the template hasn't been used yet (send_count 0
        # implies no real client has received it under the old copy).
        stored_ver = existing.get("_seed_version", 0)
        if stored_ver < _SEED_VERSION and existing.get("send_count", 0) == 0:
            refresh = {
                "name": tpl["name"],
                "subject": tpl["subject"],
                "body_html": tpl["body_html"],
                "is_system": True,
                "_seed_version": _SEED_VERSION,
                "updated_at": now,
            }
            await db.email_templates.update_one({"_id": existing["_id"]},
                                                {"$set": refresh})


# ============================================================
# Variable renderer  ({{ user.name }}, {{ invoice.number }}, ...)
# ============================================================
_TAG_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _get(ctx: dict, path: str) -> str:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    if cur is None:
        return ""
    return str(cur)


def render(template_str: str, ctx: dict) -> str:
    return _TAG_RE.sub(lambda mm: _get(ctx, mm.group(1)), template_str or "")


def wrap_html(inner_html: str) -> str:
    """Wrap a raw HTML fragment in the Intercloud brand chrome."""
    if "<html" in (inner_html or "").lower():
        return inner_html
    return _WRAPPER.replace("{body}", inner_html)


def _portal_urls(invoice_id: Optional[str] = None) -> dict:
    origin = os.environ.get("REACT_APP_BACKEND_URL", "")
    return {
        "login_url": f"{origin}/portal/login",
        "invoice_url": f"{origin}/portal/client/invoices" + (f"/{invoice_id}" if invoice_id else ""),
    }


def _fmt_idr(v: float | int) -> str:
    try:
        return f"Rp {int(v):,.0f}".replace(",", ".")
    except Exception:
        return f"Rp {v}"


def build_context(*, user: dict = None, invoice: dict = None, order: dict = None,
                  extra: dict = None) -> dict:
    ctx: dict = {}
    if user:
        ctx["user"] = {
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "company": user.get("company", "") or "",
            "id": str(user.get("_id") or user.get("id") or ""),
        }
    if invoice:
        iid = str(invoice.get("_id") or invoice.get("id") or "")
        ctx["invoice"] = {
            "id": iid,
            "number": invoice.get("number", ""),
            "total": invoice.get("total", 0),
            "total_fmt": _fmt_idr(invoice.get("total", 0)),
            "due_date": invoice.get("due_date", ""),
            "status": invoice.get("status", ""),
        }
        ctx["portal"] = _portal_urls(invoice_id=iid)
    else:
        ctx["portal"] = _portal_urls()
    if order:
        oid = str(order.get("_id") or order.get("id") or "")
        ctx["order"] = {
            "id": oid,
            "id_short": oid[-6:] if oid else "",
            "product_name": order.get("product_name", ""),
            "status": order.get("status", ""),
        }
    if extra:
        ctx.update(extra)
    return ctx


# ============================================================
# Send + log
# ============================================================
async def _log_send(db, *, event_key: str, template_id: Optional[str], to_email: str,
                    subject: str, status: str, delivered_via: str, error: Optional[str] = None,
                    invoice_id: Optional[str] = None, order_id: Optional[str] = None,
                    user_id: Optional[str] = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "event_key": event_key,
        "template_id": template_id,
        "to_email": to_email,
        "subject": subject,
        "status": status,
        "delivered_via": delivered_via,
        "error": error,
        "sent_at": now if status == "sent" else None,
        "invoice_id": invoice_id,
        "order_id": order_id,
        "user_id": user_id,
        "created_at": now,
    }
    await db.email_logs.insert_one(doc)


async def send_via_template(db, *, event_key: str, to_email: str, ctx: dict,
                            invoice_id: Optional[str] = None,
                            order_id: Optional[str] = None,
                            user_id: Optional[str] = None) -> dict:
    """Resolve the event_key → active template, render, send via SMTP, log the outcome.

    Never raises — returns a dict `{status, delivered_via, error}` so callers
    (order flow, register flow, scheduler) can never break user actions.
    """
    tpl = await db.email_templates.find_one({"event_key": event_key, "is_active": True})
    if not tpl:
        await _log_send(db, event_key=event_key, template_id=None, to_email=to_email,
                        subject=f"[{event_key}]", status="skipped", delivered_via="none",
                        error="template disabled or missing",
                        invoice_id=invoice_id, order_id=order_id, user_id=user_id)
        return {"status": "skipped", "error": "template disabled or missing"}
    subject = render(tpl["subject"], ctx)
    body = wrap_html(render(tpl["body_html"], ctx))
    tpl_id = str(tpl["_id"])
    return await deliver(
        db, to_email=to_email, subject=subject, body_html=body,
        event_key=event_key, template_id=tpl_id,
        invoice_id=invoice_id, order_id=order_id, user_id=user_id,
    )


async def deliver(db, *, to_email: str, subject: str, body_html: str,
                  event_key: str = "manual", template_id: Optional[str] = None,
                  invoice_id: Optional[str] = None, order_id: Optional[str] = None,
                  user_id: Optional[str] = None) -> dict:
    """Low-level dispatch (SMTP or skip). Writes to `email_logs`."""
    smtp = await iv2.get_settings(db, "smtp")
    if not smtp or not smtp.get("enabled"):
        log.info(f"[email:{event_key}] SMTP not configured; would send to {to_email} · {subject}")
        await _log_send(db, event_key=event_key, template_id=template_id, to_email=to_email,
                        subject=subject, status="skipped", delivered_via="log",
                        error="SMTP integration disabled",
                        invoice_id=invoice_id, order_id=order_id, user_id=user_id)
        return {"status": "skipped", "delivered_via": "log", "error": "SMTP integration disabled"}
    try:
        iv2.SMTPMailer(smtp).send(to=to_email, subject=subject, html=body_html)
        await _log_send(db, event_key=event_key, template_id=template_id, to_email=to_email,
                        subject=subject, status="sent", delivered_via="smtp",
                        invoice_id=invoice_id, order_id=order_id, user_id=user_id)
        if template_id:
            try:
                await db.email_templates.update_one(
                    {"_id": ObjectId(template_id)},
                    {"$set": {"last_sent_at": datetime.now(timezone.utc).isoformat()},
                     "$inc": {"send_count": 1}},
                )
            except Exception:
                pass
        return {"status": "sent", "delivered_via": "smtp"}
    except Exception as e:
        log.exception(f"[email:{event_key}] delivery failed → {to_email}")
        await _log_send(db, event_key=event_key, template_id=template_id, to_email=to_email,
                        subject=subject, status="failed", delivered_via="smtp",
                        error=f"{type(e).__name__}: {e}",
                        invoice_id=invoice_id, order_id=order_id, user_id=user_id)
        return {"status": "failed", "delivered_via": "smtp", "error": f"{type(e).__name__}: {e}"}


# ============================================================
# Event hook helpers (called from routes.py)
# ============================================================
async def on_user_registered(db, user_doc: dict) -> None:
    ctx = build_context(user=user_doc)
    await send_via_template(db, event_key="welcome", to_email=user_doc["email"],
                            ctx=ctx, user_id=str(user_doc.get("_id") or ""))


async def on_order_created(db, order_doc: dict, user_doc: dict) -> None:
    ctx = build_context(user=user_doc, order=order_doc)
    await send_via_template(db, event_key="order_confirmation",
                            to_email=user_doc["email"], ctx=ctx,
                            order_id=str(order_doc.get("_id") or ""),
                            user_id=str(user_doc.get("_id") or ""))


async def on_invoice_generated(db, invoice_doc: dict, user_doc: dict,
                               order_doc: dict = None) -> None:
    ctx = build_context(user=user_doc, invoice=invoice_doc, order=order_doc)
    await send_via_template(db, event_key="invoice_generated",
                            to_email=user_doc["email"], ctx=ctx,
                            invoice_id=str(invoice_doc.get("_id") or ""),
                            order_id=str(order_doc.get("_id") or "") if order_doc else None,
                            user_id=str(user_doc.get("_id") or ""))


async def on_password_reset(db, user_doc: dict, reset_url: str) -> None:
    ctx = build_context(user=user_doc, extra={"reset_url": reset_url})
    await send_via_template(db, event_key="password_reset",
                            to_email=user_doc["email"], ctx=ctx,
                            user_id=str(user_doc.get("_id") or ""))


# ============================================================
# Scheduler — invoice reminders + suspension
# ============================================================
# Templates keyed by their scheduled offset (event_key → offset_days).
_SCHEDULED_EVENTS = {
    "invoice_reminder_d3": -3,
    "invoice_due": 0,
    "invoice_overdue_d1": 1,
    "invoice_overdue_d3": 3,
    "invoice_overdue_d7": 7,
    "service_suspension": 8,
}


async def _sent_today(db, invoice_id: str, event_key: str) -> bool:
    today = datetime.now(timezone.utc).date().isoformat()
    hit = await db.email_logs.find_one({
        "event_key": event_key,
        "invoice_id": invoice_id,
        "status": {"$in": ["sent", "skipped"]},
        "created_at": {"$gte": today},
    })
    return hit is not None


async def run_invoice_reminder_sweep(db, *, now: Optional[datetime] = None) -> dict:
    """Scan invoices, fire any due reminder emails, suspend on D+8.

    Returns a summary dict for observability.
    Idempotent per (invoice, event, day) via `_sent_today` guard.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()
    fired = {k: 0 for k in _SCHEDULED_EVENTS}
    suspended = 0

    # Only unpaid/overdue invoices are eligible.
    cursor = db.invoices.find({"status": {"$in": ["unpaid", "overdue"]}})
    async for inv in cursor:
        due_str = inv.get("due_date") or ""
        try:
            due_dt = datetime.strptime(due_str, "%Y-%m-%d").date()
        except Exception:
            continue
        delta_days = (today - due_dt).days     # negative → before due; positive → past due
        for event_key, offset in _SCHEDULED_EVENTS.items():
            if delta_days != offset:
                continue
            iid = str(inv["_id"])
            if await _sent_today(db, iid, event_key):
                continue
            user = await db.users.find_one({"_id": inv["user_id"]})
            if not user:
                continue
            ctx = build_context(user=user, invoice=inv)
            res = await send_via_template(
                db, event_key=event_key, to_email=user["email"], ctx=ctx,
                invoice_id=iid, user_id=str(user["_id"]),
            )
            if res.get("status") in ("sent", "skipped"):
                fired[event_key] += 1
            # Service suspension side-effect
            if event_key == "service_suspension":
                await db.services.update_many(
                    {"user_id": user["_id"], "status": "active"},
                    {"$set": {"status": "suspended", "suspended_at": now.isoformat(),
                              "suspended_reason": f"invoice {inv.get('number','')} overdue >8d"}},
                )
                suspended += 1
    return {"date": today.isoformat(), "fired": fired, "services_suspended": suspended}


# Scheduler singleton
_scheduler = None


def start_scheduler(db):
    """Fire up an in-process APScheduler that runs the sweep hourly.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except Exception as e:  # noqa: BLE001
        log.warning(f"APScheduler not available: {e}")
        return None

    sched = AsyncIOScheduler(timezone="Asia/Jakarta")

    async def _tick():
        try:
            summary = await run_invoice_reminder_sweep(db)
            log.info(f"[email-scheduler] sweep result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[email-scheduler] tick failed: {e}")

    # Run at :05 every hour (a small delay after the top of the hour so servers
    # coming back up don't collide with other jobs).
    sched.add_job(_tick, CronTrigger(minute=5))
    # Also run once at startup so the effect is immediate on deploy.
    sched.add_job(_tick, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=10))
    sched.start()
    _scheduler = sched
    log.info("[email-scheduler] started (hourly sweep)")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
