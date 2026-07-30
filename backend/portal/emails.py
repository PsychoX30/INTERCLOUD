"""Automated email/notification engine for the Intercloud portal.

Three tiers of trigger:

  * INSTANT - fired synchronously (best-effort) from event hooks in routes.py:
      welcome, order_confirmation, invoice_generated, password_reset

  * SCHEDULED - fired by an APScheduler cron job that runs every hour and
    scans unpaid invoices, matching them to templates keyed by their
    `offset_days` value relative to `due_date`:
      -3  → invoice_reminder_d3
       0  → invoice_due
      +1  → invoice_overdue_d1
      +3  → invoice_overdue_d3
      +7  → invoice_overdue_d7
      +8  → service_suspension  (also flips linked services to `suspended`)

  * ON-DEMAND - admin explicitly triggers a blast:
      maintenance, newsletter

Every send is written to `email_logs` with an audit trail (status,
error, delivered_via). If the SMTP integration isn't configured, sends
are logged with status=`skipped` and delivered_via=`log` so nothing
crashes and the admin can see why nothing arrived.
"""

from __future__ import annotations
import asyncio
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
# Default template library - seeded on first startup
# ============================================================
# HTML wrapper applied to every rendered body so newsletters and
# transactional mail share consistent branding.
BRAND_HEADER = "#0a2350"
BRAND_ACCENT = "#f5b120"
LOGO_URL = "https://intercloud-digital.com/og-logo.png"

_WRAPPER_TEMPLATE = """<!doctype html>
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
      <div style="margin-top:8px;color:#94a3b8;font-size:10px">This is an automated message from the Intercloud Client Portal. Please do not reply directly - use the portal or contact channels above.</div>
    </div>
  </div>
</body></html>"""

# Kept for callers that import the constant; resolved at import time using the
# static LOGO_URL default. New code should pass an explicit logo_url to
# wrap_html() (defined below) which allows runtime overrides via Admin ▸ Branding.
_WRAPPER = _WRAPPER_TEMPLATE.replace("__LOGO__", LOGO_URL)


# Bump this whenever the shipped default templates meaningfully change - startup
# will then refresh any unedited system templates in place.
_SEED_VERSION = 5


DEFAULT_TEMPLATES: list[dict] = [
    {
        "event_key": "welcome",
        "name": "Welcome - onboarding klien baru",
        "subject": "Selamat datang di Intercloud, {{user.name}} - Portal Anda siap digunakan",
        "body_html": (
            "<p style='font-size:15px'>Halo <b>{{user.name}}</b>,</p>"
            "<p>Terima kasih telah memilih <b>PT Intercloud Digital Inovasi</b>. Akun Client Portal Anda sudah aktif dan siap digunakan.</p>"
            "<p><b>Panduan memulai:</b></p>"
            "<ol style='padding-left:20px;margin:8px 0 16px;line-height:1.7'>"
            "  <li><b>Masuk ke portal</b> menggunakan alamat email ini pada halaman login.</li>"
            "  <li><b>Lengkapi profil &amp; data penagihan</b> (alamat, NPWP) melalui menu <i>Settings</i>.</li>"
            "  <li><b>Pesan layanan</b> Cloud, VPS, Hosting, Colocation, Dedicated Server, atau konektivitas dari menu <i>Order</i>.</li>"
            "  <li><b>Kelola tagihan</b> - lihat, unduh PDF, dan bayar invoice online (Duitku / transfer bank) di menu <i>Invoices</i>.</li>"
            "  <li><b>Butuh bantuan?</b> Buka tiket teknis atau billing 24/7 dari menu <i>Support Tickets</i>.</li>"
            "  <li><b>Amankan akun Anda</b> dengan mengaktifkan 2FA di menu <i>Security</i>.</li>"
            "</ol>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.login_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;letter-spacing:.02em'>Buka Client Portal &rarr;</a>"
            "</p>"
            "<p>Tim kami siap membantu kapan pun di "
            "<a href='mailto:support@intercloud-digital.com'>support@intercloud-digital.com</a> "
            "atau WhatsApp di +62 878-1239-7187.</p>"
            "<p style='margin-top:24px'>Salam hangat,<br><b>Tim Intercloud</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "order_confirmation",
        "name": "Order confirmation - instant",
        "subject": "Order received - {{order.product_name}} (Ref #{{order.id_short}})",
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
        "name": "Invoice issued - instant (D-14 baseline)",
        "subject": "Invoice {{invoice.number}} - {{invoice.total_fmt}} (due {{invoice.due_date}})",
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
            " · Mandiri - 1240011911816 (a.n. PT Intercloud Digital Inovasi)<br>"
            " · BCA - 4730862038 (a.n. PT Intercloud Digital Inovasi)</p>"
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
        "name": "Payment reminder - 3 days before due",
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
            "<p>If payment has already been submitted, please disregard this notice - our systems will update within 1-2 business hours after settlement.</p>"
            "<p style='margin-top:24px'>Kind regards,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": -3,
        "send_time": "08:00",
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "invoice_due",
        "name": "Payment due - today",
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
        "name": "Overdue notice - D+1",
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
        "name": "Overdue notice - D+3",
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
        "name": "Overdue notice - D+7 (final warning)",
        "subject": "URGENT - invoice {{invoice.number}} 7 days past due · services will be suspended",
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
        "name": "Service suspension - D+8",
        "subject": "Notice of service suspension - invoice {{invoice.number}}",
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
            "<p style='color:#64748b;font-size:12px;margin-top:18px'>If you did not request a password reset, no action is required - your password will remain unchanged. "
            "For security concerns, contact <a href='mailto:security@intercloud-digital.com'>security@intercloud-digital.com</a> immediately.</p>"
            "<p style='margin-top:24px'>Kind regards,<br><b>Intercloud Security Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "payment_received",
        "name": "Payment received - invoice paid",
        "subject": "Payment received - invoice {{invoice.number}}",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>We are pleased to confirm that your payment for invoice <b>{{invoice.number}}</b> "
            "(<b>{{invoice.total_fmt}}</b>) has been <b>received and verified</b>. Thank you.</p>"
            "<p>Any services that were suspended due to this invoice have been "
            "<b>reactivated automatically</b>. No further action is required on your part.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.invoice_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>View receipt in portal &rarr;</a>"
            "</p>"
            "<p>Should you require an official receipt or have any billing questions, our finance team "
            "is available at <a href='mailto:finance@intercloud-digital.com'>finance@intercloud-digital.com</a> "
            "or WhatsApp +62 878-1239-7187.</p>"
            "<p>We appreciate your business and continued trust in our services.</p>"
            "<p style='margin-top:24px'>Respectfully,<br><b>Intercloud Finance Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "maintenance",
        "name": "Scheduled maintenance notification",
        "subject": "Scheduled maintenance notice - {{maintenance.title}}",
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
        "event_key": "hosting_provisioned",
        "name": "Hosting account ready - credentials",
        "subject": "Your hosting account is ready - {{hosting.domain}}",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Great news! Your hosting service <b>{{service.product_name}}</b> has been "
            "<b>provisioned successfully</b> and is now active. Below are your account details:</p>"
            "<table style='width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:10px;overflow:hidden'>"
            "  <tr><td style='padding:10px 14px;color:#64748b;font-size:12px;width:32%'>Control panel</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{hosting.panel}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Domain</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{hosting.domain}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Username</td><td style='padding:10px 14px;font-family:monospace;color:#0f172a'>{{hosting.username}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Password</td><td style='padding:10px 14px;font-family:monospace;color:#0f172a'>{{hosting.password}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Panel URL</td><td style='padding:10px 14px'><a href='{{hosting.panel_url}}'>{{hosting.panel_url}}</a></td></tr>"
            "</table>"
            "<p style='margin:22px 0'>"
            "  <a href='{{hosting.panel_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Log in to control panel &rarr;</a>"
            "</p>"
            "<p style='color:#64748b;font-size:12px'>For your security, we strongly recommend changing this password immediately after your first login. "
            "Never share these credentials via unsecured channels.</p>"
            "<p>You can also manage this service anytime from your "
            "<a href='{{portal.login_url}}'>Intercloud Client Portal</a>. Should you need any assistance, "
            "our support team is available at <a href='mailto:support@intercloud-digital.com'>support@intercloud-digital.com</a> "
            "or WhatsApp +62 878-1239-7187.</p>"
            "<p style='margin-top:24px'>Best regards,<br><b>Intercloud Provisioning Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "vm_provisioned",
        "name": "VM ready - handover VPS/Cloud",
        "subject": "VPS Anda siap digunakan - {{vm.hostname}}",
        "body_html": (
            "<p>Halo <b>{{user.name}}</b>,</p>"
            "<p>Kabar baik! Layanan <b>{{service.product_name}}</b> Anda telah "
            "<b>selesai diprovisioning</b> dan siap digunakan. Berikut detail server Anda:</p>"
            "<table style='width:100%;border-collapse:collapse;margin:16px 0;background:#f8fafc;border-radius:10px;overflow:hidden'>"
            "  <tr><td style='padding:10px 14px;color:#64748b;font-size:12px;width:32%'>Hostname</td><td style='padding:10px 14px;font-weight:700;color:#0a2350'>{{vm.hostname}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>IP Address</td><td style='padding:10px 14px;font-family:monospace;color:#0f172a'>{{vm.ip}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Sistem Operasi</td><td style='padding:10px 14px;color:#0f172a'>{{vm.os}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>VMID / Node</td><td style='padding:10px 14px;font-family:monospace;color:#0f172a'>{{vm.vmid}} @ {{vm.node}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Username</td><td style='padding:10px 14px;font-family:monospace;color:#0f172a'>{{vm.username}}</td></tr>"
            "  <tr style='border-top:1px solid #e2e8f0'><td style='padding:10px 14px;color:#64748b;font-size:12px'>Password awal</td><td style='padding:10px 14px;font-family:monospace;color:#0f172a'>{{vm.password}}</td></tr>"
            "</table>"
            "<p>Akses server via SSH: <code style='background:#f1f5f9;padding:2px 8px;border-radius:6px'>ssh {{vm.username}}@{{vm.ip}}</code></p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.login_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Kelola VM di Client Portal &rarr;</a>"
            "</p>"
            "<p style='color:#64748b;font-size:12px'>Demi keamanan, segera ganti password ini setelah login pertama. "
            "Jangan bagikan kredensial melalui saluran yang tidak aman.</p>"
            "<p style='margin-top:24px'>Salam,<br><b>Tim Provisioning Intercloud</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "domain_expiry_reminder",
        "name": "Domain expiry reminder",
        "subject": "Action required - domain {{domain.name}} expires in {{domain.days_left}} day(s)",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>This is a friendly reminder that your domain <b>{{domain.name}}</b> is due to expire on "
            "<b>{{domain.expires_at}}</b> (<b>{{domain.days_left}} day(s)</b> from now).</p>"
            "<p>To avoid service interruption, DNS downtime, or losing the domain to the redemption period, "
            "please renew it before the expiry date.</p>"
            "<p style='margin:22px 0'>"
            "  <a href='{{portal.login_url}}' style='display:inline-block;padding:12px 26px;background:#0a2350;color:#fff;text-decoration:none;border-radius:8px;font-weight:700'>Renew domain in portal &rarr;</a>"
            "</p>"
            "<p>If auto-renew is enabled and your balance or payment method is in order, no action is needed - "
            "we will process the renewal automatically.</p>"
            "<p>Questions? Contact <a href='mailto:support@intercloud-digital.com'>support@intercloud-digital.com</a> "
            "or WhatsApp +62 878-1239-7187.</p>"
            "<p style='margin-top:24px'>Best regards,<br><b>Intercloud Domain Team</b></p>"
        ),
        "offset_days": None,
        "send_time": None,
        "is_active": True,
        "is_system": True,
    },
    {
        "event_key": "newsletter",
        "name": "Newsletter - monthly (default shell)",
        "subject": "Intercloud Insights - {{month.name}}",
        "body_html": (
            "<p>Dear <b>{{user.name}}</b>,</p>"
            "<p>Welcome to this month's edition of <b>Intercloud Insights</b> - our digest of product updates, industry perspectives, and behind-the-scenes stories from PT Intercloud Digital Inovasi.</p>"
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
    DB migration). We do NOT clobber templates whose `send_count > 0` - those
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


def wrap_html(inner_html: str, logo_url: str | None = None) -> str:
    """Wrap a raw HTML fragment in the Intercloud brand chrome. If `logo_url`
    is provided (typically fetched from Admin ▸ Branding) it overrides the
    hardcoded default."""
    if "<html" in (inner_html or "").lower():
        return inner_html
    wrapper = _WRAPPER_TEMPLATE.replace("__LOGO__", logo_url or LOGO_URL)
    return wrapper.replace("{body}", inner_html)


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

    Never raises - returns a dict `{status, delivered_via, error}` so callers
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


async def on_hosting_provisioned(db, user_doc: dict, service_doc: dict, credentials: dict) -> None:
    """Hosting account credentials email - fired after successful live panel provisioning."""
    ctx = build_context(user=user_doc, extra={
        "hosting": credentials,
        "service": {
            "product_name": service_doc.get("product_name", ""),
            "next_renewal": service_doc.get("next_renewal", ""),
        },
    })
    await send_via_template(db, event_key="hosting_provisioned",
                            to_email=user_doc["email"], ctx=ctx,
                            user_id=str(user_doc.get("_id") or ""))


async def on_vm_provisioned(db, user_doc: dict, service_doc: dict, vm: dict) -> None:
    """VPS/Cloud VM handover email - fired after successful live Proxmox provisioning."""
    ctx = build_context(user=user_doc, extra={
        "vm": vm,
        "service": {
            "product_name": service_doc.get("product_name", ""),
            "next_renewal": service_doc.get("next_renewal", ""),
        },
    })
    await send_via_template(db, event_key="vm_provisioned",
                            to_email=user_doc["email"], ctx=ctx,
                            user_id=str(user_doc.get("_id") or ""))


async def on_invoice_paid(db, invoice_doc: dict, user_doc: dict) -> None:
    """Payment-received confirmation - fired by the payment webhook (and any
    other flow that marks an invoice paid and wants the client notified)."""
    ctx = build_context(user=user_doc, invoice=invoice_doc)
    await send_via_template(db, event_key="payment_received",
                            to_email=user_doc["email"], ctx=ctx,
                            invoice_id=str(invoice_doc.get("_id") or ""),
                            user_id=str(user_doc.get("_id") or ""))


# ============================================================
# Global settings helper (settings collection: {key, value})
# ============================================================
async def get_setting(db, key: str, default=None):
    doc = await db.settings.find_one({"key": key})
    return doc.get("value") if doc and "value" in doc else default


# ============================================================
# Scheduler - invoice reminders + suspension
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


_reminder_sweep_lock = asyncio.Lock()


async def run_invoice_reminder_sweep(db, *, now: Optional[datetime] = None) -> dict:
    """Scan invoices, fire any due reminder emails, suspend on D+8.

    Returns a summary dict for observability.
    Idempotent per (invoice, event, day) via `_sent_today` guard; the module
    lock keeps a manual run-now from racing the scheduled tick (the guard is
    check-then-insert, so two concurrent sweeps could double-send).
    """
    async with _reminder_sweep_lock:
        return await _run_invoice_reminder_sweep_inner(db, now=now)


async def _run_invoice_reminder_sweep_inner(db, *, now: Optional[datetime] = None) -> dict:
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


# ============================================================
# Renewal automation - auto-generate renewal invoices
# ============================================================
_CYCLE_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "annual": 12}


def _add_months(date_str: str, months: int) -> str:
    """Advance an ISO date by N calendar months, clamping the day
    (e.g. 2026-01-31 +1m → 2026-02-28)."""
    import calendar
    from datetime import date as _date
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    y = d.year + (d.month - 1 + months) // 12
    mo = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return _date(y, mo, day).isoformat()


async def _next_invoice_number(db, offset: int = 0) -> str:
    """Same numbering scheme as routes._next_number (kept local to avoid a
    circular import): INV-{year}-{seq:05d}. Derives seq from the highest
    existing number for the year (count-based numbering collides after
    deletions or under concurrent writers)."""
    year = datetime.now(timezone.utc).year
    prefix = f"INV-{year}-"
    last = await (db.invoices.find({"number": {"$regex": f"^{prefix}"}})
                  .sort("number", -1).limit(1).to_list(1))
    if last:
        try:
            seq = int(last[0]["number"][len(prefix):]) + 1
        except Exception:
            seq = await db.invoices.count_documents({}) + 1
    else:
        seq = await db.invoices.count_documents({}) + 1
    return f"{prefix}{seq + offset:05d}"


async def run_renewal_invoice_sweep(db, *, now: Optional[datetime] = None) -> dict:
    """Generate renewal invoices for active services whose `next_renewal`
    falls within `settings.renewal_lead_days` (default 7) days.

    Duplicate-generation guard (documented contract):
      * every renewal invoice stores `service_id` + `renewal_period`
        (= the `next_renewal` date it covers);
      * a sweep run skips any (service, period) pair that already has an
        invoice, so re-running the sweep is idempotent;
      * `services.next_renewal` is advanced by one billing-cycle interval and
        `services.last_renewal_invoice_id` is set only AFTER the invoice
        insert succeeds.

    `tax_percent` is pre-filled from `settings.default_tax_percent` (manual,
    admin-editable per invoice afterwards - never recalculated).
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()
    lead_days = int(await get_setting(db, "renewal_lead_days", 7) or 7)
    tax_percent = float(await get_setting(db, "default_tax_percent", 11.0))
    horizon = (today + timedelta(days=lead_days)).isoformat()
    generated, skipped_existing, errors = 0, 0, 0

    cursor = db.services.find({"status": "active",
                               "auto_renew": {"$ne": False},
                               "next_renewal": {"$gt": "", "$lte": horizon}})
    async for svc in cursor:
        period = svc.get("next_renewal") or ""
        try:
            datetime.strptime(period, "%Y-%m-%d")
        except Exception:
            continue
        sid = str(svc["_id"])
        if await db.invoices.find_one({"service_id": sid, "renewal_period": period}):
            skipped_existing += 1
            continue
        user = await db.users.find_one({"_id": svc["user_id"]})
        if not user:
            continue
        cycle = (svc.get("billing_cycle") or "monthly").lower()
        months = _CYCLE_MONTHS.get(cycle, 1)
        amount = round(float(svc.get("price_monthly") or 0) * months, 2)
        if amount <= 0:
            continue
        new_renewal = _add_months(period, months)
        svc_label = svc.get("name") or svc.get("product_name") or "Service"
        item = {"description": f"Renewal - {svc_label} ({cycle}) · {period} → {new_renewal}",
                "qty": 1, "unit_price": amount, "total": amount}
        tax_amount = round(amount * tax_percent / 100, 2)
        inv = {
            "number": "",  # assigned in the retry loop below
            "user_id": svc["user_id"],
            "items": [item],
            "subtotal": amount,
            "tax_percent": tax_percent,
            "tax_amount": tax_amount,
            "total": round(amount + tax_amount, 2),
            "due_date": period,
            "status": "unpaid",
            "payment_method": None,
            "paid_at": None,
            "notes": f"Auto-generated renewal invoice for {svc_label} - period starting {period}.",
            "service_id": sid,
            "renewal_period": period,
            "created_at": now.isoformat(),
        }
        # Unique-number retry: concurrent writers (admin API, parallel sweeps)
        # can race on the same sequence; regenerate with an offset and retry.
        r = None
        for attempt in range(5):
            inv["number"] = await _next_invoice_number(db, offset=attempt)
            try:
                r = await db.invoices.insert_one(inv)
                break
            except Exception as e:
                if "duplicate key" in str(e).lower() and attempt < 4:
                    continue
                log.exception(f"[renewal] invoice insert failed for service {sid}")
                r = None
                break
        if r is None:
            errors += 1
            continue
        inv["_id"] = r.inserted_id
        # Advance the renewal date ONLY after the invoice exists.
        await db.services.update_one(
            {"_id": svc["_id"]},
            {"$set": {"next_renewal": new_renewal,
                      "last_renewal_invoice_id": str(r.inserted_id)}},
        )
        try:
            await on_invoice_generated(db, inv, user)
        except Exception:
            log.exception(f"[renewal] invoice email failed for {inv['number']}")
        generated += 1

    return {"date": today.isoformat(), "horizon": horizon,
            "generated": generated, "skipped_existing": skipped_existing,
            "errors": errors}


# ============================================================
# NOC - proactive MikroTik reachability polling
# ============================================================
# Ran every 5 minutes on the SAME scheduler as email reminders + renewal
# sweeps (per PRD constraint: reuse the existing AsyncIOScheduler). Each
# tick pings every device via `MikrotikClient.test_connection()` in a
# threadpool (librouteros is sync), stores a `noc_probes` sample, updates
# `noc_device_state`, and - on a transition - writes a `noc_events` row +
# fires an alert email to `settings.noc_alert_recipients`.
async def run_noc_probe_sweep(db) -> dict:
    """Poll every MikroTik device once. Fire alerts on up→down / down→up transitions."""
    from . import integrations_v2 as _iv2
    now_iso = datetime.now(timezone.utc).isoformat()
    devices = await db.mikrotik_devices.find({}).to_list(500)
    probed = 0
    transitions = 0
    for d in devices:
        # Best-effort probe in threadpool - never crash the sweep
        try:
            import asyncio as _a
            client = _iv2.MikrotikClient(d)
            result = await _a.get_event_loop().run_in_executor(None, client.test_connection)
            ok = bool(result.get("ok"))
            message = result.get("message") or ""
        except Exception as e:
            ok, message = False, f"probe exception: {type(e).__name__}: {e}"

        probed += 1
        # Sample row (used for 24h uptime %)
        await db.noc_probes.insert_one({
            "device_id": d["_id"],
            "at": now_iso,
            "ok": ok,
            "message": message[:400],
        })

        # Compare to last known state (default "unknown" → any status triggers an event)
        state = await db.noc_device_state.find_one({"device_id": d["_id"]}) or {}
        prev_status = state.get("status") or "unknown"
        new_status = "up" if ok else "down"
        await db.noc_device_state.update_one(
            {"device_id": d["_id"]},
            {"$set": {"device_id": d["_id"],
                      "status": new_status,
                      "last_probe_at": now_iso,
                      "last_message": message[:400],
                      **({"last_change_at": now_iso}
                         if prev_status != new_status else {})}},
            upsert=True,
        )

        # Fire an event ONLY on real transitions (avoid alert-storm on flaps)
        if prev_status != new_status and prev_status != "unknown":
            transitions += 1
            evt_type = "device_up" if ok else "device_down"
            evt = {
                "device_id": d["_id"],
                "device_name": d.get("name") or "unnamed",
                "device_host": d.get("host") or "",
                "type": evt_type,
                "message": message[:400],
                "at": now_iso,
                "email_notified": False,
            }
            r = await db.noc_events.insert_one(evt)
            evt["_id"] = r.inserted_id
            try:
                sent = await _dispatch_noc_alert(db, d, evt)
                if sent:
                    await db.noc_events.update_one({"_id": r.inserted_id},
                                                   {"$set": {"email_notified": True}})
            except Exception:
                log.exception(f"[noc] alert dispatch failed for device {d.get('name')}")

    return {"at": now_iso, "probed": probed, "transitions": transitions}


async def _dispatch_noc_alert(db, device: dict, event: dict) -> bool:
    """Send an email alert for a device state transition.

    Recipients come from `settings.noc_alert_recipients` (list of emails)
    or fall back to all users with role=admin when the list is empty."""
    doc = await db.settings.find_one({"key": "noc_alert_recipients"}) or {}
    recipients = list(doc.get("value") or [])
    if not recipients:
        cur = db.users.find({"role": "admin", "is_active": {"$ne": False}}, {"email": 1})
        recipients = [u["email"] async for u in cur if u.get("email")]
    if not recipients:
        return False
    evt_type = event.get("type") or "device_down"
    down = evt_type == "device_down"
    color = "#dc2626" if down else "#059669"
    verb = "DOWN" if down else "recovered"
    subject = f"[NOC] {device.get('name','unnamed')} is {verb}"
    body = f"""
      <h2 style="color:{color};margin:0 0 8px 0">Device {verb}</h2>
      <p style="margin:0 0 12px 0">A MikroTik reachability probe transitioned this device to
      <b style="color:{color}">{evt_type.replace('_', ' ')}</b>.</p>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <tr><td style="padding:6px 0;color:#64748b;width:130px">Device</td><td><b>{device.get('name','unnamed')}</b></td></tr>
        <tr><td style="padding:6px 0;color:#64748b">Host</td><td>{device.get('host','')}</td></tr>
        <tr><td style="padding:6px 0;color:#64748b">Site</td><td>{device.get('site') or '-'}</td></tr>
        <tr><td style="padding:6px 0;color:#64748b">Detected at</td><td>{event.get('at','')}</td></tr>
        <tr><td style="padding:6px 0;color:#64748b;vertical-align:top">Probe result</td>
            <td style="font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#334155">{event.get('message','')}</td></tr>
      </table>
      <p style="margin-top:16px;font-size:12px;color:#64748b">Alerts fire only on transitions,
      so you will get exactly one email per state change (no flap-storm).</p>
    """
    ok = False
    for to_email in recipients:
        try:
            r = await deliver(db, to_email=to_email, subject=subject,
                              body_html=wrap_html(body), event_key="noc_alert")
            if r.get("status") == "sent":
                ok = True
        except Exception:
            log.exception(f"[noc] alert send failed for {to_email}")
    return ok


async def run_noc_probe_retention(db) -> dict:
    """Daily housekeeping for the high-frequency `noc_probes` collection.

    (a) Rolls up per-device daily uptime % into `noc_daily_uptime`
        (device_id, date, uptime_pct, sample_count) for every full past day.
    (b) Deletes raw probe samples older than `settings.noc_probe_retention_days`
        (default 30). NEVER touches `audit_logs` or `noc_events` - those are
        permanent history."""
    doc = await db.settings.find_one({"key": "noc_probe_retention_days"}) or {}
    try:
        retention_days = int(doc.get("value") or 30)
    except (TypeError, ValueError):
        retention_days = 30
    retention_days = max(1, retention_days)
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    rolled = 0
    pipeline = [
        {"$project": {"device_id": 1, "ok": 1, "day": {"$substr": ["$at", 0, 10]}}},
        {"$match": {"day": {"$lt": today}}},
        {"$group": {"_id": {"device_id": "$device_id", "day": "$day"},
                     "total": {"$sum": 1},
                     "up": {"$sum": {"$cond": ["$ok", 1, 0]}}}},
    ]
    async for row in db.noc_probes.aggregate(pipeline):
        did = row["_id"]["device_id"]
        day = row["_id"]["day"]
        total = int(row.get("total") or 0)
        if not total:
            continue
        await db.noc_daily_uptime.update_one(
            {"device_id": did, "date": day},
            {"$set": {"uptime_pct": round(int(row.get("up") or 0) / total * 100, 2),
                      "sample_count": total,
                      "computed_at": now.isoformat()}},
            upsert=True,
        )
        rolled += 1

    cutoff = (now - timedelta(days=retention_days)).isoformat()
    res = await db.noc_probes.delete_many({"at": {"$lt": cutoff}})
    summary = {"at": now.isoformat(), "rolled_days": rolled,
               "deleted_probes": res.deleted_count,
               "retention_days": retention_days}
    log.info(f"[noc-retention] {summary}")
    return summary


# Scheduler singleton
_scheduler = None


# ============================================================
# Domain expiry reminders - D-30/D-14/D-7/D-1 + status transitions
# ============================================================
_DOMAIN_REMINDER_OFFSETS = {"d30": 30, "d14": 14, "d7": 7, "d1": 1}


async def run_domain_expiry_sweep(db, *, now: Optional[datetime] = None) -> dict:
    """Scan koleksi domains: kirim pengingat menjelang expiry dan geser status
    active → expiring (≤30 hari) → expired. Idempotent per (domain, offset)
    via marker `reminders_sent` pada dokumen domain."""
    now = now or datetime.now(timezone.utc)
    today = now.date()
    fired = {k: 0 for k in _DOMAIN_REMINDER_OFFSETS}
    marked_expiring = 0
    marked_expired = 0
    cursor = db.domains.find({"status": {"$in": ["active", "expiring"]},
                              "expires_at": {"$nin": [None, ""]}})
    async for dom in cursor:
        try:
            exp = datetime.strptime((dom.get("expires_at") or "")[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        days_left = (exp - today).days
        if days_left < 0:
            await db.domains.update_one({"_id": dom["_id"]}, {"$set": {"status": "expired"}})
            marked_expired += 1
            continue
        if days_left <= 30 and dom.get("status") == "active":
            await db.domains.update_one({"_id": dom["_id"]}, {"$set": {"status": "expiring"}})
            marked_expiring += 1
        for key, offset in _DOMAIN_REMINDER_OFFSETS.items():
            if days_left != offset:
                continue
            if (dom.get("reminders_sent") or {}).get(key):
                continue
            user = await db.users.find_one({"_id": dom["user_id"]})
            if not user:
                continue
            ctx = build_context(user=user, extra={"domain": {
                "name": dom["domain"],
                "expires_at": (dom.get("expires_at") or "")[:10],
                "days_left": days_left,
            }})
            res = await send_via_template(db, event_key="domain_expiry_reminder",
                                          to_email=user["email"], ctx=ctx,
                                          user_id=str(user["_id"]))
            if res.get("status") in ("sent", "skipped"):
                await db.domains.update_one(
                    {"_id": dom["_id"]},
                    {"$set": {f"reminders_sent.{key}": today.isoformat()}})
                fired[key] += 1
    return {"date": today.isoformat(), "fired": fired,
            "marked_expiring": marked_expiring, "marked_expired": marked_expired}


# ============================================================
# NOC - DDoS threshold evaluation + incident detection
# ============================================================
def _ddos_attack_type(flow: dict) -> str:
    proto = (flow.get("protocol") or "").lower()
    port = str(flow.get("src_port") or flow.get("dst_port") or "")
    if port == "53":
        return "DNS Amplification"
    if port in ("80", "443"):
        return "HTTP Flood"
    if proto == "udp":
        return "UDP Flood"
    if proto in ("tcp", "tcp-syn"):
        return "SYN Flood"
    return "Traffic Anomaly"


def _ddos_severity(ratio: float) -> str:
    if ratio >= 4:
        return "critical"
    if ratio >= 2:
        return "high"
    return "medium"


async def run_ddos_detection_sweep(db) -> dict:
    """Evaluasi aturan ambang batas trafik terhadap sampel torch MikroTik live.
    Membuka insiden DDoS (dedupe per target aktif), auto-blackhole bila rule
    memintanya, dan auto-resolve insiden yang trafiknya sudah normal."""
    from . import integrations_v2 as _iv2
    import asyncio as _a
    now_iso = datetime.now(timezone.utc).isoformat()
    rules = await db.ddos_threshold_rules.find({"enabled": True}).to_list(100)
    if not rules:
        return {"at": now_iso, "skipped": "no enabled rules"}
    devices = await db.mikrotik_devices.find({}).to_list(100)

    # ---- Sample per-target traffic via torch (aggregate dst_address) ----
    targets: dict = {}   # ip -> {bps, pps, flow, device_name}
    sampled_devices = 0
    for d in devices:
        iface = d.get("main_interface") or d.get("interface") or "ether1"
        try:
            client = _iv2.MikrotikClient(d)
            res = await _a.get_event_loop().run_in_executor(
                None, lambda c=client, i=iface: c.torch(interface=i, duration=2))
        except Exception:
            continue
        if not res.get("ok"):
            continue
        sampled_devices += 1
        for f in res.get("rows", []):
            ip = (f.get("dst_address") or "").split("/")[0]
            if not ip or ip in ("0.0.0.0", "255.255.255.255"):
                continue
            t = targets.setdefault(ip, {"bps": 0, "pps": 0, "flow": f,
                                        "device": d.get("name") or "unnamed",
                                        "device_doc": d})
            t["bps"] += f.get("rx_rate", 0) + f.get("tx_rate", 0)
            t["pps"] += f.get("rx_packets", 0) + f.get("tx_packets", 0)

    # ---- Evaluate rules against samples ----
    opened, blackholed = 0, 0
    breached_ips = set()
    for ip, t in targets.items():
        for rule in rules:
            value = t["pps"] if rule.get("metric") == "pps" else t["bps"]
            threshold = float(rule.get("threshold") or 0)
            if threshold <= 0 or value <= threshold:
                continue
            breached_ips.add(ip)
            existing = await db.ddos_incidents.find_one({"target": ip, "status": "active"})
            if existing:
                await db.ddos_incidents.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"pps": t["pps"], "bps": t["bps"],
                              "severity": _ddos_severity(value / threshold)}})
                continue
            incident = {
                "target": ip,
                "attack_type": _ddos_attack_type(t["flow"]),
                "pps": t["pps"],
                "bps": t["bps"],
                "severity": _ddos_severity(value / threshold),
                "status": "active",
                "action": rule.get("action", "alert"),
                "rule_id": str(rule["_id"]),
                "rule_name": rule.get("name", ""),
                "device": t["device"],
                "started_at": now_iso,
                "ended_at": None,
                "notified": [],
            }
            r = await db.ddos_incidents.insert_one(incident)
            incident["_id"] = r.inserted_id
            opened += 1
            if rule.get("action") == "alert_blackhole":
                try:
                    client = _iv2.MikrotikClient(t["device_doc"])
                    bh = await _a.get_event_loop().run_in_executor(
                        None, lambda c=client, p=f"{ip}/32", n=rule.get("name", ""):
                        c.blackhole_add(p, comment=f"auto-mitigasi ({n})"))
                    ok = not bh.get("error")
                except Exception as e:
                    ok, bh = False, {"error": str(e)}
                await db.blackhole_log.insert_one({
                    "prefix": f"{ip}/32", "action": "add",
                    "by": f"auto-mitigasi ({rule.get('name', '')})",
                    "source": "auto", "device": t["device"],
                    "ok": ok, "detail": str(bh)[:300], "at": now_iso,
                })
                if ok:
                    blackholed += 1
                    await db.ddos_incidents.update_one(
                        {"_id": r.inserted_id}, {"$set": {"status": "mitigated"}})
            try:
                await dispatch_ddos_notifications(db, incident)
            except Exception:
                log.exception("[ddos] notification dispatch failed")
            break  # satu insiden per target per sweep

    # ---- Auto-resolve incidents whose targets are back to normal ----
    resolved = 0
    if sampled_devices:
        async for inc in db.ddos_incidents.find({"status": "active"}):
            if inc["target"] not in breached_ips:
                await db.ddos_incidents.update_one(
                    {"_id": inc["_id"]},
                    {"$set": {"status": "resolved", "ended_at": now_iso}})
                resolved += 1

    return {"at": now_iso, "devices_sampled": sampled_devices,
            "targets_seen": len(targets), "incidents_opened": opened,
            "auto_blackholed": blackholed, "auto_resolved": resolved}


async def dispatch_ddos_notifications(db, incident: dict) -> list:
    """Kirim alert insiden DDoS ke saluran notifikasi aktif (event 'ddos').
    Email dikirim live via SMTP; whatsapp/telegram/webhook dicatat di
    ddos_notify_log (dispatch live per channel menyusul sesuai kredensial)."""
    channels = await db.notif_channels.find({"enabled": True, "events": "ddos"}).to_list(50)
    notified = []
    subject = (f"[DDoS] {incident.get('severity', '').upper()} - "
               f"{incident.get('attack_type', '')} ke {incident.get('target', '')}")
    body = (
        f"<h2 style='color:#dc2626;margin:0 0 8px 0'>Insiden DDoS terdeteksi</h2>"
        f"<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<tr><td style='padding:6px 0;color:#64748b;width:130px'>Target</td><td><b>{incident.get('target', '')}</b></td></tr>"
        f"<tr><td style='padding:6px 0;color:#64748b'>Jenis</td><td>{incident.get('attack_type', '')}</td></tr>"
        f"<tr><td style='padding:6px 0;color:#64748b'>Severity</td><td>{incident.get('severity', '')}</td></tr>"
        f"<tr><td style='padding:6px 0;color:#64748b'>Trafik</td><td>{incident.get('bps', 0):,} bps / {incident.get('pps', 0):,} pps</td></tr>"
        f"<tr><td style='padding:6px 0;color:#64748b'>Rule</td><td>{incident.get('rule_name', '')}</td></tr>"
        f"<tr><td style='padding:6px 0;color:#64748b'>Aksi</td><td>{incident.get('action', '')}</td></tr>"
        f"<tr><td style='padding:6px 0;color:#64748b'>Waktu</td><td>{incident.get('started_at', '')}</td></tr>"
        f"</table>"
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    for ch in channels:
        target = ch.get("target", "")
        status = "queued"
        if ch.get("type") == "email":
            try:
                r = await deliver(db, to_email=target, subject=subject,
                                  body_html=wrap_html(body), event_key="ddos_alert")
                status = r.get("status", "failed")
            except Exception:
                status = "failed"
        elif ch.get("type") == "telegram":
            try:
                from . import integrations_v2 as _iv2
                s = await _iv2.get_settings(db, "telegram")
                if s and s.get("enabled"):
                    text = (f"[DDoS {incident.get('severity', '').upper()}] "
                            f"{incident.get('attack_type', '')} ke {incident.get('target', '')} - "
                            f"{incident.get('bps', 0):,} bps / {incident.get('pps', 0):,} pps "
                            f"(rule: {incident.get('rule_name', '')})")
                    chat_id = target if target and not target.startswith("@") else None
                    res = await _iv2.TelegramNotifier(s).send(text, chat_id=chat_id)
                    status = "sent" if res.get("ok") else "failed"
                else:
                    status = "skipped"
            except Exception:
                status = "failed"
        elif ch.get("type") == "webhook":
            try:
                import httpx as _hx
                payload = {
                    "text": subject,
                    "incident": {
                        "target": incident.get("target", ""),
                        "attack_type": incident.get("attack_type", ""),
                        "severity": incident.get("severity", ""),
                        "bps": incident.get("bps", 0),
                        "pps": incident.get("pps", 0),
                        "rule": incident.get("rule_name", ""),
                        "action": incident.get("action", ""),
                        "started_at": incident.get("started_at", ""),
                    },
                }
                async with _hx.AsyncClient(timeout=8.0) as c:
                    r = await c.post(target, json=payload)
                status = "sent" if r.status_code < 300 else f"failed ({r.status_code})"
            except Exception:
                status = "failed"
        await db.ddos_notify_log.insert_one({
            "incident_id": str(incident.get("_id") or ""),
            "target": incident.get("target", ""),
            "channel_type": ch.get("type", ""),
            "channel_target": target,
            "status": status,
            "at": now_iso,
        })
        notified.append(f"{ch.get('type')}:{target}")
    if notified:
        await db.ddos_incidents.update_one(
            {"_id": incident.get("_id")}, {"$set": {"notified": notified}})
    return notified


# ------------------------------------------------------------------
# Live traffic collector (MikroTik) - feeds the client Traffic Report
# ------------------------------------------------------------------
async def sample_service_traffic(db, service_id: str, device: dict, interface: str,
                                 *, now: Optional[datetime] = None) -> Optional[dict]:
    """Take ONE live rate sample from the router and store it in traffic_samples."""
    from . import integrations_v2 as iv2
    now = now or datetime.now(timezone.utc)
    res = await asyncio.get_event_loop().run_in_executor(
        None, lambda: iv2.MikrotikClient(device).traffic_monitor(interface))
    if not res or res.get("error"):
        return None

    def _num(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    from zoneinfo import ZoneInfo
    local = now.astimezone(ZoneInfo("Asia/Jakarta"))
    doc = {
        "service_id": service_id,
        "at": now.isoformat(),
        "t": local.strftime("%H:00"),
        "in_mbps": round(_num(res.get("rx-bits-per-second")) / 1_000_000, 2),
        "out_mbps": round(_num(res.get("tx-bits-per-second")) / 1_000_000, 2),
    }
    await db.traffic_samples.insert_one(dict(doc))
    try:
        await db.traffic_monthly.update_one(
            {"service_id": service_id, "month": local.strftime("%Y-%m")},
            {"$inc": {"in_gb": round(doc["in_mbps"] * 3600 / 8 / 1024, 3),
                      "out_gb": round(doc["out_mbps"] * 3600 / 8 / 1024, 3),
                      "samples": 1}},
            upsert=True)
    except Exception:
        pass
    doc.pop("_id", None)
    return doc


async def run_traffic_sample_sweep(db, *, now: Optional[datetime] = None) -> dict:
    """Hourly collector: one live sample per mapped service, 48h retention."""
    from . import integrations_v2 as iv2
    from bson import ObjectId
    now = now or datetime.now(timezone.utc)
    svcs = await db.services.find({
        "config.traffic_device_id": {"$exists": True, "$ne": ""},
        "config.traffic_interface": {"$exists": True, "$ne": ""},
    }).to_list(500)
    sampled = errors = 0
    device_cache: dict = {}
    for s in svcs:
        cfg = s.get("config") or {}
        did = str(cfg.get("traffic_device_id"))
        iface = cfg.get("traffic_interface")
        device = device_cache.get(did)
        if device is None:
            if did == "legacy":
                s2 = await iv2.get_settings(db, "mikrotik")
                device = ({**(s2.get("credentials") or {})}
                          if (s2 and s2.get("enabled")) else False)
            else:
                try:
                    device = await db.mikrotik_devices.find_one({"_id": ObjectId(did)}) or False
                except Exception:
                    device = False
            device_cache[did] = device
        if not device:
            errors += 1
            continue
        try:
            r = await sample_service_traffic(db, str(s["_id"]), device, iface, now=now)
            sampled += 1 if r else 0
            errors += 0 if r else 1
        except Exception:
            errors += 1
    cutoff = (now - timedelta(hours=48)).isoformat()
    try:
        await db.traffic_samples.delete_many({"at": {"$lt": cutoff}})
    except Exception:
        pass
    return {"services": len(svcs), "sampled": sampled, "errors": errors}


# ------------------------------------------------------------------
# Laporan bulanan (tagihan + trafik) ke email support - dokumentasi
# ------------------------------------------------------------------
async def run_monthly_report(db, *, month: Optional[str] = None) -> dict:
    """Build + email a monthly billing & traffic summary. `month` = 'YYYY-MM'
    (default: previous month). Sent to settings key `monthly_report_email`,
    falling back to ADMIN_EMAIL env, then support@intercloud-digital.com."""
    from bson import ObjectId
    now = datetime.now(timezone.utc)
    if not month:
        month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    q_month = {"$regex": f"^{month}"}

    issued = await db.invoices.find({"created_at": q_month}).to_list(3000)
    paid = await db.invoices.find({"status": "paid", "paid_at": q_month}).to_list(3000)
    outstanding = await db.invoices.find({"status": {"$in": ["unpaid", "overdue"]}}).to_list(3000)
    credits = await db.credit_notes.find({"status": "applied", "applied_at": q_month}).to_list(1000)
    new_clients = await db.users.count_documents({"role": "client", "created_at": q_month})
    new_orders = await db.orders.count_documents({"created_at": q_month})

    tm = await db.traffic_monthly.find({"month": month}).sort("in_gb", -1).to_list(500)
    svc_ids = []
    for t in tm:
        try:
            svc_ids.append(ObjectId(t["service_id"]))
        except Exception:
            pass
    svc_map = {}
    if svc_ids:
        async for s in db.services.find({"_id": {"$in": svc_ids}}):
            svc_map[str(s["_id"])] = s.get("name") or s.get("product_name", "")

    summary = {
        "invoices_issued": len(issued),
        "invoices_issued_total": round(sum(i.get("total", 0) for i in issued), 2),
        "invoices_paid": len(paid),
        "invoices_paid_total": round(sum(i.get("total", 0) for i in paid), 2),
        "outstanding_total": round(sum(i.get("total", 0) for i in outstanding), 2),
        "credit_notes_applied": len(credits),
        "credit_notes_total": round(sum(c.get("amount", 0) for c in credits), 2),
        "new_clients": new_clients,
        "new_orders": new_orders,
        "traffic_services": len(tm),
        "traffic_in_gb": round(sum(t.get("in_gb", 0) for t in tm), 2),
        "traffic_out_gb": round(sum(t.get("out_gb", 0) for t in tm), 2),
    }

    def _row(label, value):
        return (f"<tr style='border-top:1px solid #e2e8f0'>"
                f"<td style='padding:9px 14px;color:#64748b;font-size:12px'>{label}</td>"
                f"<td style='padding:9px 14px;font-weight:700;color:#0a2350;text-align:right'>{value}</td></tr>")

    billing_rows = "".join([
        _row("Invoice diterbitkan", f"{summary['invoices_issued']} · {_fmt_idr(summary['invoices_issued_total'])}"),
        _row("Invoice dibayar", f"{summary['invoices_paid']} · {_fmt_idr(summary['invoices_paid_total'])}"),
        _row("Outstanding saat ini (unpaid + overdue)", _fmt_idr(summary["outstanding_total"])),
        _row("Credit note diterapkan", f"{summary['credit_notes_applied']} · {_fmt_idr(summary['credit_notes_total'])}"),
        _row("Klien baru", str(summary["new_clients"])),
        _row("Order baru", str(summary["new_orders"])),
    ])
    if tm:
        traffic_rows = "".join(
            f"<tr style='border-top:1px solid #e2e8f0'>"
            f"<td style='padding:8px 14px;font-size:12px;color:#0a2350'>{svc_map.get(t['service_id'], t['service_id'])}</td>"
            f"<td style='padding:8px 14px;font-size:12px;text-align:right'>{round(t.get('in_gb', 0), 2)} GB</td>"
            f"<td style='padding:8px 14px;font-size:12px;text-align:right'>{round(t.get('out_gb', 0), 2)} GB</td></tr>"
            for t in tm[:25])
        traffic_html = (
            "<h3 style='color:#0a2350;margin:24px 0 8px'>Trafik per layanan</h3>"
            "<table style='width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden'>"
            "<tr><th style='padding:9px 14px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>Layanan</th>"
            "<th style='padding:9px 14px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Inbound</th>"
            "<th style='padding:9px 14px;text-align:right;font-size:11px;color:#64748b;text-transform:uppercase'>Outbound</th></tr>"
            f"{traffic_rows}</table>"
            f"<p style='font-size:12px;color:#64748b'>Total: {summary['traffic_in_gb']} GB in / {summary['traffic_out_gb']} GB out "
            f"dari {summary['traffic_services']} layanan terpantau.</p>")
    else:
        traffic_html = ("<h3 style='color:#0a2350;margin:24px 0 8px'>Trafik per layanan</h3>"
                        "<p style='font-size:13px;color:#64748b'>Belum ada data trafik untuk bulan ini - "
                        "petakan layanan ke interface MikroTik di Admin - Services.</p>")

    inner = (
        f"<p>Laporan bulanan otomatis periode <b>{month}</b> untuk dokumentasi internal.</p>"
        "<h3 style='color:#0a2350;margin:16px 0 8px'>Ringkasan tagihan</h3>"
        "<table style='width:100%;border-collapse:collapse;background:#f8fafc;border-radius:10px;overflow:hidden'>"
        f"{billing_rows}</table>"
        f"{traffic_html}"
        "<p style='margin-top:20px;font-size:12px;color:#64748b'>Email ini dikirim otomatis oleh Intercloud Portal setiap tanggal 1.</p>"
    )
    to_email = (await get_setting(db, "monthly_report_email", None)
                or os.environ.get("ADMIN_EMAIL")
                or "support@intercloud-digital.com")
    # Arsipkan laporan (1 dokumen per bulan) agar PDF bisa diunduh ulang dari Finance.
    await db.monthly_reports.update_one(
        {"month": month},
        {"$set": {"month": month, "summary": summary, "body_html": inner,
                  "to_email": to_email,
                  "generated_at": now.isoformat()}},
        upsert=True)
    delivery = await deliver(
        db, to_email=to_email,
        subject=f"[Laporan Bulanan] {month} - ringkasan tagihan & trafik Intercloud",
        body_html=wrap_html(inner), event_key="monthly_report")
    await db.monthly_reports.update_one(
        {"month": month}, {"$set": {"last_delivery": delivery}})
    return {"month": month, "to_email": to_email,
            "delivery": delivery, "summary": summary}


# ------------------------------------------------------------------
# Ringkasan mingguan (Senin pagi WIB) ke email support
# ------------------------------------------------------------------
async def run_weekly_summary(db, *, now: Optional[datetime] = None) -> dict:
    """Order baru 7 hari terakhir, tiket terbuka saat ini, dan invoice jatuh
    tempo 7 hari ke depan (termasuk yang sudah overdue)."""
    now = now or datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=7)).isoformat()
    week_ahead = (now + timedelta(days=7)).date().isoformat()
    orders = await db.orders.find(
        {"created_at": {"$gte": week_ago}}).sort("created_at", -1).to_list(300)
    tickets = await db.tickets.find(
        {"status": {"$nin": ["resolved", "closed"]}}).sort("updated_at", -1).to_list(300)
    due_invoices = await db.invoices.find(
        {"status": {"$in": ["unpaid", "overdue"]},
         "due_date": {"$lte": week_ahead}}).sort("due_date", 1).to_list(500)

    summary = {
        "new_orders": len(orders),
        "open_tickets": len(tickets),
        "invoices_due": len(due_invoices),
        "invoices_due_total": round(sum(i.get("total", 0) for i in due_invoices), 2),
    }

    def _table(headers, rows):
        head = "".join(
            f"<th style='padding:8px 12px;text-align:left;font-size:11px;color:#64748b;text-transform:uppercase'>{h}</th>"
            for h in headers)
        body = "".join(
            "<tr style='border-top:1px solid #e2e8f0'>" +
            "".join(f"<td style='padding:8px 12px;font-size:12px;color:#0f172a'>{c}</td>" for c in r) +
            "</tr>" for r in rows)
        return ("<table style='width:100%;border-collapse:collapse;background:#f8fafc;"
                f"border-radius:10px;overflow:hidden'><tr>{head}</tr>{body}</table>")

    def _more(total):
        return (f"<p style='font-size:11px;color:#64748b;margin:4px 0 0'>"
                f"dan {total - 10} lainnya di portal.</p>") if total > 10 else ""

    if orders:
        orders_html = _table(
            ["Produk", "Klien", "Status", "Tanggal"],
            [[o.get("product_name", ""), o.get("user_name") or o.get("user_email", ""),
              o.get("status", ""), (o.get("created_at") or "")[:10]] for o in orders[:10]],
        ) + _more(len(orders))
    else:
        orders_html = "<p style='font-size:13px;color:#64748b'>Tidak ada order baru minggu ini.</p>"

    if tickets:
        tickets_html = _table(
            ["Nomor", "Subjek", "Prioritas", "Status"],
            [[t.get("number", ""), (t.get("subject") or "")[:60], t.get("priority", ""),
              t.get("status", "")] for t in tickets[:10]],
        ) + _more(len(tickets))
    else:
        tickets_html = "<p style='font-size:13px;color:#64748b'>Tidak ada tiket terbuka. Kerja bagus!</p>"

    if due_invoices:
        inv_html = _table(
            ["Nomor", "Jatuh Tempo", "Status", "Total"],
            [[i.get("number", ""), (i.get("due_date") or "")[:10], i.get("status", ""),
              _fmt_idr(i.get("total", 0))] for i in due_invoices[:10]],
        ) + _more(len(due_invoices))
    else:
        inv_html = "<p style='font-size:13px;color:#64748b'>Tidak ada invoice jatuh tempo minggu ini.</p>"

    inner = (
        f"<p>Ringkasan mingguan otomatis per <b>{now.date().isoformat()}</b>.</p>"
        f"<h3 style='color:#0a2350;margin:18px 0 8px'>Order baru 7 hari terakhir ({summary['new_orders']})</h3>{orders_html}"
        f"<h3 style='color:#0a2350;margin:22px 0 8px'>Tiket terbuka saat ini ({summary['open_tickets']})</h3>{tickets_html}"
        f"<h3 style='color:#0a2350;margin:22px 0 8px'>Invoice jatuh tempo minggu ini ({summary['invoices_due']} &middot; {_fmt_idr(summary['invoices_due_total'])})</h3>{inv_html}"
        "<p style='margin-top:20px;font-size:12px;color:#64748b'>Email ini dikirim otomatis oleh Intercloud Portal setiap Senin pagi.</p>"
    )
    to_email = (await get_setting(db, "monthly_report_email", None)
                or os.environ.get("ADMIN_EMAIL")
                or "support@intercloud-digital.com")
    delivery = await deliver(
        db, to_email=to_email,
        subject=f"[Ringkasan Mingguan] {now.date().isoformat()} - order, tiket & invoice jatuh tempo",
        body_html=wrap_html(inner), event_key="weekly_summary")
    return {"date": now.date().isoformat(), "to_email": to_email,
            "delivery": delivery, "summary": summary}


def _public_ssl_days_left(host: str, port: int = 443, timeout: float = 6.0) -> int:
    """Sisa hari sertifikat SSL publik sebuah host (blocking, panggil via to_thread)."""
    import ssl as _ssl
    import socket as _socket
    ctx = _ssl.create_default_context()
    with _socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            cert = ssock.getpeercert()
    expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    return (expires - datetime.now(timezone.utc)).days


async def run_health_alert_sweep(db, disk_threshold: float = 85.0,
                                 ssl_days_threshold: int = 14):
    """Email peringatan ke admin bila disk hampir penuh atau SSL akan
    kedaluwarsa. Dedup: maksimal 1 email per hari (klaim atomik via _id)."""
    import shutil as _sh
    import asyncio as _aio
    issues = []

    du = _sh.disk_usage("/")
    disk_pct = round(du.used / du.total * 100, 1)
    if disk_pct >= disk_threshold:
        free_gb = round(du.free / 1024 ** 3, 1)
        total_gb = round(du.total / 1024 ** 3, 1)
        issues.append(f"Disk hampir penuh: {disk_pct}% terpakai (sisa {free_gb} GB dari {total_gb} GB). "
                      "Bersihkan log/backup lama atau tambah kapasitas disk.")

    origin = (os.environ.get("REACT_APP_BACKEND_URL") or "").strip().rstrip("/")
    if origin.startswith("https://"):
        host = origin[8:].split("/")[0].split(":")[0]
        try:
            days = await _aio.to_thread(_public_ssl_days_left, host)
            if days <= ssl_days_threshold:
                issues.append(f"Sertifikat SSL {host} akan kedaluwarsa dalam {days} hari. "
                              "Pastikan certbot.timer aktif atau perbarui manual: certbot renew.")
        except Exception as e:  # noqa: BLE001
            log.warning(f"[health-alert] cek SSL {host} gagal: {e}")

    if not issues:
        return {"issues": 0, "delivery": None}

    from pymongo.errors import DuplicateKeyError
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        await db.health_alert_log.insert_one({
            "_id": f"health-alert-{today}", "date": today, "issues": issues,
            "created_at": datetime.now(timezone.utc).isoformat()})
    except DuplicateKeyError:
        return {"issues": len(issues), "delivery": {"status": "deduped"}}

    rows = "".join(f"<li style='margin:6px 0'>{i}</li>" for i in issues)
    inner = (
        "<h2 style='margin:0 0 12px'>Peringatan Kesehatan Server</h2>"
        f"<p>Pemeriksaan otomatis menemukan <b>{len(issues)} masalah kritis</b> pada server portal:</p>"
        f"<ul>{rows}</ul>"
        "<p>Detail lengkap dan status terkini: buka <b>Admin &gt; Diagnostics &gt; System Health</b> di portal.</p>"
    )
    to_email = (await get_setting(db, "monthly_report_email", None)
                or os.environ.get("ADMIN_EMAIL")
                or "support@intercloud-digital.com")
    delivery = await deliver(
        db, to_email=to_email,
        subject=f"[PERINGATAN] Kesehatan server: {len(issues)} masalah kritis terdeteksi",
        body_html=wrap_html(inner), event_key="health_alert")
    return {"issues": len(issues), "to_email": to_email, "delivery": delivery}


def start_scheduler(db):
    """Fire up an in-process APScheduler that runs the sweep hourly.

    Safe to call multiple times - subsequent calls are no-ops.
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

    async def _renewal_tick():
        try:
            summary = await run_renewal_invoice_sweep(db)
            log.info(f"[renewal-scheduler] sweep result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[renewal-scheduler] tick failed: {e}")

    async def _noc_tick():
        try:
            summary = await run_noc_probe_sweep(db)
            log.info(f"[noc-scheduler] sweep result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[noc-scheduler] tick failed: {e}")

    async def _domain_tick():
        try:
            summary = await run_domain_expiry_sweep(db)
            log.info(f"[domain-scheduler] sweep result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[domain-scheduler] tick failed: {e}")

    async def _ddos_tick():
        try:
            summary = await run_ddos_detection_sweep(db)
            log.info(f"[ddos-scheduler] sweep result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[ddos-scheduler] tick failed: {e}")

    # Run at :05 every hour (a small delay after the top of the hour so servers
    # coming back up don't collide with other jobs).
    sched.add_job(_tick, CronTrigger(minute=5))
    # Also run once at startup so the effect is immediate on deploy.
    sched.add_job(_tick, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=10))
    # Renewal invoice sweep - same scheduler instance, its own hourly slot.
    sched.add_job(_renewal_tick, CronTrigger(minute=20))
    sched.add_job(_renewal_tick, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=20))
    # NOC probe sweep - every 5 minutes, on the SAME scheduler (PRD constraint).
    sched.add_job(_noc_tick, CronTrigger(minute="*/5"))
    sched.add_job(_noc_tick, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=30))
    # Domain expiry sweep - hourly at :35 on the SAME scheduler.
    sched.add_job(_domain_tick, CronTrigger(minute=35))
    sched.add_job(_domain_tick, "date", run_date=datetime.now(timezone.utc) + timedelta(seconds=40))
    # DDoS threshold evaluation - every 5 minutes (offset dari NOC probe) on the SAME scheduler.
    sched.add_job(_ddos_tick, CronTrigger(minute="2-59/5"))

    # Traffic collector - hourly live samples from mapped MikroTik interfaces.
    async def _traffic_tick():
        try:
            summary = await run_traffic_sample_sweep(db)
            if summary["services"]:
                log.info(f"[traffic-scheduler] sweep result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[traffic-scheduler] tick failed: {e}")

    sched.add_job(_traffic_tick, CronTrigger(minute=50))
    sched.add_job(_traffic_tick, "date",
                  run_date=datetime.now(timezone.utc) + timedelta(seconds=50))

    # Laporan bulanan ke email support - tanggal 1 pukul 06:30 WIB.
    async def _monthly_report_tick():
        try:
            result = await run_monthly_report(db)
            log.info(f"[monthly-report] {result.get('month')} -> {result.get('to_email')} "
                     f"({(result.get('delivery') or {}).get('status')})")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[monthly-report] tick failed: {e}")

    sched.add_job(_monthly_report_tick, CronTrigger(day=1, hour=6, minute=30))

    # Ringkasan mingguan ke email support - setiap Senin 07:00 WIB.
    async def _weekly_summary_tick():
        try:
            result = await run_weekly_summary(db)
            log.info(f"[weekly-summary] {result.get('date')} -> {result.get('to_email')} "
                     f"({(result.get('delivery') or {}).get('status')})")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[weekly-summary] tick failed: {e}")

    sched.add_job(_weekly_summary_tick, CronTrigger(day_of_week="mon", hour=7, minute=0))

    # Peringatan kesehatan server (disk hampir penuh / SSL akan kedaluwarsa)
    # - setiap hari 07:30 WIB, dedup 1 email per hari di dalam sweep-nya.
    async def _health_alert_tick():
        try:
            result = await run_health_alert_sweep(db)
            if result.get("issues"):
                log.info(f"[health-alert] {result}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[health-alert] tick failed: {e}")

    sched.add_job(_health_alert_tick, CronTrigger(hour=7, minute=30))

    async def _noc_retention_tick():
        try:
            summary = await run_noc_probe_retention(db)
            log.info(f"[noc-retention-scheduler] result: {summary}")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[noc-retention-scheduler] tick failed: {e}")

    # NOC probe retention/rollup - daily at 03:40 (same scheduler, alongside backup cron slot).
    sched.add_job(_noc_retention_tick, CronTrigger(hour=3, minute=40))

    async def _backup_tick():
        try:
            import pathlib
            from .backups import run_mongodump
            blob, filename = await run_mongodump()
            pathlib.Path("/app/backups").mkdir(parents=True, exist_ok=True)
            with open(f"/app/backups/{filename}", "wb") as f:
                f.write(blob)
            await db.backup_history.insert_one({
                "filename": filename, "path": f"/app/backups/{filename}",
                "size_bytes": len(blob), "kind": "scheduled", "by": "scheduler",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            # Retensi: simpan 14 backup terjadwal terakhir
            old = await db.backup_history.find({"kind": "scheduled"}).sort("created_at", -1).skip(14).to_list(50)
            for o in old:
                try:
                    os.remove(o.get("path", ""))
                except OSError:
                    pass
                await db.backup_history.delete_one({"_id": o["_id"]})
            log.info(f"[backup-scheduler] daily backup ok: {filename} ({len(blob)} bytes)")
        except Exception as e:  # noqa: BLE001
            log.exception(f"[backup-scheduler] tick failed: {e}")

    # Backup database harian - 03:30 (same scheduler).
    sched.add_job(_backup_tick, CronTrigger(hour=3, minute=30))
    sched.start()
    _scheduler = sched
    log.info("[email-scheduler] started (hourly reminder + renewal sweeps + NOC 5-min probes)")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
