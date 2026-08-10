"""PDF/HTML documents: invoice & quotation rendering, resend email.

Split from the former monolithic routes.py - behavior preserved 1:1.
"""
import os
import asyncio
import logging
import secrets
import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from .. import models as m
from ..auth import (
    verify_password, hash_password, create_access_token,
    get_current_user, get_current_admin, get_current_staff, get_current_content,
    require_roles, sales_can_access,
    STAFF_ROLES, FINANCE_ROLES, BILLING_ROLES, CATALOG_ROLES,
    OPS_ROLES, USER_MGMT_ROLES, TICKET_ROLES, CONTENT_ROLES,
)
from ..audit import log_audit, serialize as _serialize_audit
from ..secretbox import (dec_value as _sb_dec, enc_value as _sb_enc,
                         decrypt_config as _sb_dec_config)
from .. import integrations_v2 as iv2
from .shared import _get_db, _oid, _sales_scope_filter  # noqa: E402
from portal import emails as _emails  # noqa: E402

router = APIRouter()


# ============================================================
# PDF (HTML/PDF) documents - Invoice & Quotation
# Rendered as an HTML preview by default; add ?format=pdf for a real
# WeasyPrint-rendered downloadable .pdf that matches the WHMCS-style layout.
# ============================================================
from fastapi.responses import HTMLResponse, Response


# Long-form English/Indonesian date used inside the document
def _long_date(iso_or_ymd: str) -> str:
    if not iso_or_ymd:
        return "-"
    try:
        s = iso_or_ymd[:10]
        dt = datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        try:
            dt = datetime.fromisoformat(iso_or_ymd.replace("Z", "+00:00"))
        except Exception:
            return iso_or_ymd
    # e.g. "Thursday, June 18th, 2026"
    day = dt.day
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return dt.strftime(f"%A, %B {day}{suffix}, %Y")


def _idr(v) -> str:
    """Format IDR as 'Rp3,300,000.00' (WHMCS-style)."""
    try:
        f = float(v or 0)
    except Exception:
        f = 0.0
    return "Rp" + f"{f:,.2f}"


def _period_label(item: dict) -> str:
    """If item has period_start / period_end (YYYY-MM-DD), append ' (dd/mm/yyyy - dd/mm/yyyy)'."""
    ps, pe = item.get("period_start"), item.get("period_end")
    if not (ps and pe):
        return ""
    try:
        s = datetime.strptime(ps[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        e = datetime.strptime(pe[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        return f" ({s} - {e})"
    except Exception:
        return ""


def _addressed_to_block(u: dict) -> str:
    company = u.get("company") or u.get("name") or ""
    attn = u.get("attention") or u.get("name") or ""
    lines = []
    if company:
        lines.append(f"<div style='font-weight:700;color:#111'>{company}</div>")
    if attn:
        lines.append(f"<div>ATTN: {attn}</div>")
    if u.get("address_line1"):
        lines.append(f"<div>{u['address_line1']}</div>")
    if u.get("address_line2"):
        lines.append(f"<div>{u['address_line2']}</div>")
    city_line = ", ".join([x for x in [u.get("city"), u.get("province"), u.get("postal_code")] if x])
    if city_line:
        lines.append(f"<div>{city_line}</div>")
    if u.get("country"):
        lines.append(f"<div>{u['country']}</div>")
    return "\n".join(lines)


# Diagonal corner ribbon (top-right), color depends on status
def _corner_ribbon(status: str) -> str:
    s = (status or "").lower()
    if s == "paid":
        color = "#22c55e"  # green
        label = "PAID"
    elif s == "overdue":
        color = "#dc2626"  # red
        label = "OVERDUE"
    elif s == "cancelled":
        color = "#64748b"
        label = "CANCELLED"
    elif s == "unpaid":
        color = "#f59e0b"  # amber
        label = "UNPAID"
    elif s in ("draft", "sent"):
        color = "#0a2350"  # navy
        label = s.upper()
    elif s == "accepted":
        color = "#22c55e"
        label = "ACCEPTED"
    elif s == "rejected":
        color = "#dc2626"
        label = "REJECTED"
    elif s == "expired":
        color = "#64748b"
        label = "EXPIRED"
    else:
        color = "#f5b120"
        label = (status or "").upper() or "&nbsp;"
    return f"""
    <div class="ribbon-wrap">
      <div class="ribbon" style="background:{color}">{label}</div>
    </div>
    """


COMPANY_HEADER_HTML = """
<div class="company-block">
  <div style="font-weight:800;letter-spacing:.02em;color:#0a2350">PT. INTERCLOUD DIGITAL INOVASI</div>
  <div>Menara Cakrawala Lt 12, Unit 1205A</div>
  <div>Jl. M.H. Thamrin No.9, RT.2/RW.1,</div>
  <div>Kb. Sirih, Kec. Menteng Kota Jakarta Pusat,</div>
  <div>Daerah Khusus Ibukota Jakarta,</div>
  <div>10340</div>
  <div style="margin-top:6px">NPWP : 62.573.806.7-021.000</div>
</div>
"""


from portal.branding import get_branding as _get_branding_dict, DEFAULTS as _BRANDING_DEFAULTS, BRANDING_KEYS as _BRANDING_KEYS


LOGO_URL = _BRANDING_DEFAULTS["logo_dark"]


def _pdf_template(
    *,
    doc_kind: str,           # "invoice" or "quotation"
    number: str,
    issued_date: str,        # YYYY-MM-DD or ISO
    due_or_valid_date: str,  # YYYY-MM-DD
    due_or_valid_label: str, # "Due Date" or "Valid Until"
    items: list,
    subtotal: float,
    tax_amount: float,    total: float,
    tax_percent: float,
    credit_applied: float = 0,
    credit_notes: list = None,
    status: str,
    billed_to: dict,
    transactions: list = None,
    balance: float = None,
    notes: str = "",
    banks: list = None,
    extra_footer: str = "",
    for_pdf: bool = False,
    logo_url: str = LOGO_URL,
) -> str:
    """Renders the invoice/quotation HTML matching the reference layout."""
    transactions = transactions or []
    credit_val = ("-" + _idr(credit_applied)) if credit_applied and credit_applied > 0 else _idr(0)
    amount_due_row = ""
    if credit_applied and credit_applied > 0:
        due_val = 0 if status == "paid" else max(0, total - credit_applied)
        amount_due_row = ("<tr class='grand'><td class='lbl'>Amount Due</td>"
                          f"<td class='val'>{_idr(due_val)}</td></tr>")
    title = "Invoice" if doc_kind == "invoice" else "Quotation"
    header_title = f"{title} #{number}"

    # ---- items table (Description | Total) ----
    item_rows = "".join(
        f"<tr>"
        f"<td class='desc'>{i.get('description','')}{_period_label(i)}</td>"
        f"<td class='amt'>{_idr(i.get('total', (i.get('qty',1) * i.get('unit_price',0))))}</td>"
        f"</tr>"
        for i in items
    )

    # ---- transactions table (only if there are any) ----
    tx_rows = "".join(
        f"<tr>"
        f"<td>{_long_date(t.get('date',''))}</td>"
        f"<td>{t.get('gateway','')}</td>"
        f"<td>{t.get('transaction_id','') or '-'}</td>"
        f"<td class='amt'>{_idr(t.get('amount',0))}</td>"
        f"</tr>"
        for t in transactions
    )
    if transactions:
        bal = balance if balance is not None else max(0.0, float(total or 0) - sum(float(x.get("amount") or 0) for x in transactions))
        tx_block = f"""
        <div class="section-title">Transactions</div>
        <table class="tx">
          <thead>
            <tr>
              <th style="width:28%">Transaction Date</th>
              <th style="width:22%">Gateway</th>
              <th style="width:28%">Transaction ID</th>
              <th style="width:22%;text-align:right">Amount</th>
            </tr>
          </thead>
          <tbody>{tx_rows}</tbody>
          <tfoot>
            <tr><td colspan="3" class="bal-lbl">Balance</td><td class="amt bal-val">{_idr(bal)}</td></tr>
          </tfoot>
        </table>
        """
    else:
        tx_block = ""

    # ---- credit notes applied (detail di bawah tabel total) ----
    if credit_notes:
        cn_rows = "".join(
            f"<tr>"
            f"<td>{c.get('number', '')}</td>"
            f"<td>{c.get('reason', '') or '-'}</td>"
            f"<td>{_long_date(c.get('applied_at') or c.get('created_at', ''))}</td>"
            f"<td class='amt'>-{_idr(c.get('amount', 0))}</td>"
            f"</tr>"
            for c in credit_notes
        )
        cn_block = f"""
        <div class="section-title">Credit Notes Applied</div>
        <table class="tx">
          <thead>
            <tr>
              <th style="width:22%">Number</th>
              <th style="width:36%">Reason</th>
              <th style="width:22%">Applied Date</th>
              <th style="width:20%;text-align:right">Amount</th>
            </tr>
          </thead>
          <tbody>{cn_rows}</tbody>
        </table>
        """
    else:
        cn_block = ""

    # ---- banks (unpaid only) ----
    if banks:
        bank_rows = "".join(
            f"<div class='bank-row'><span class='bank-name'>{b['bank']}</span>"
            f"<span class='bank-num'>{b['number']}</span>"
            f"<span class='bank-holder'>A/N {b['holder']}</span></div>"
            for b in banks
        )
        bank_block = f"""
        <div class="bank-panel">
          <div class="section-title" style="margin-top:0">Payment - Bank Transfer</div>
          {bank_rows}
          <div class="bank-note">Please include invoice number <b>{number}</b> in the transfer memo. Confirmation via WhatsApp speeds up reconciliation.</div>
        </div>
        """
    else:
        bank_block = ""

    ribbon = _corner_ribbon(status)
    generated_on = _long_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Actions bar only for browser (HTML) view
    actions_bar = "" if for_pdf else (
        f'<div class="actions">'
        f'<button onclick="window.print()">Print</button>'
        f'<a class="dl" href="?format=pdf&token={{TOKEN_PLACEHOLDER}}">Download PDF</a>'
        f'</div>'
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} #{number}</title>
<style>
  @page {{ size: A4; margin: 14mm 14mm 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color:#334155; margin:0; padding:0; background:#f1f5f9; font-size:12px; line-height:1.45; }}
  .paper {{ background:#fff; padding:34px 40px 30px; max-width:800px; margin:20px auto; position:relative; box-shadow:0 6px 30px rgba(2,6,23,.08); }}

  /* Corner ribbon top-right */
  .ribbon-wrap {{ position:absolute; top:0; right:0; width:170px; height:170px; overflow:hidden; pointer-events:none; }}
  .ribbon {{ position:absolute; top:24px; right:-52px; transform:rotate(45deg); width:220px; text-align:center;
             color:#fff; font-weight:800; letter-spacing:.2em; padding:8px 0; font-size:14px;
             box-shadow:0 2px 6px rgba(0,0,0,.15); }}

  /* Header - logo sized generously so a wordmark reads cleanly on print */
  .head {{ display:flex; justify-content:space-between; align-items:center; gap:24px; }}
  .head .logo {{ flex:0 0 auto; max-width:55%; }}
  .head .logo img {{ height:130px; max-height:130px; width:auto; max-width:100%; object-fit:contain; display:block; }}
  .company-block {{ text-align:right; font-size:11.5px; color:#334155; line-height:1.55; }}

  /* Invoice title strip */
  .titlebar {{ margin-top:28px; background:#e5edf5; padding:14px 18px; }}
  .titlebar h1 {{ margin:0 0 6px 0; font-size:20px; color:#334155; font-weight:800; }}
  .titlebar .meta-line {{ font-size:12px; color:#475569; }}
  .titlebar .meta-line b {{ color:#0f172a; font-weight:600; }}

  /* Invoiced To */
  .to {{ margin-top:22px; }}
  .to .lbl {{ font-weight:700; font-size:12px; color:#111; margin-bottom:6px; }}
  .to .body {{ font-size:11.5px; color:#475569; line-height:1.6; }}

  /* Items table */
  table.items {{ width:100%; border-collapse:collapse; margin-top:22px; font-size:12px; }}
  table.items thead th {{ background:#e5edf5; color:#334155; font-weight:700; padding:9px 12px; text-align:center; border:1px solid #cbd5e1; }}
  table.items tbody td {{ padding:11px 12px; border:1px solid #e2e8f0; vertical-align:top; }}
  table.items td.desc {{ background:#fff; }}
  table.items td.amt {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}

  /* Totals block */
  .totals {{ margin-top:6px; }}
  .totals table {{ margin-left:auto; border-collapse:collapse; font-size:12px; }}
  .totals td {{ padding:7px 14px; border:1px solid #e2e8f0; }}
  .totals td.lbl {{ background:#f1f5f9; text-align:right; font-weight:700; color:#0f172a; width:170px; }}
  .totals td.val {{ text-align:right; width:170px; font-variant-numeric:tabular-nums; }}
  .totals tr.grand td.lbl,
  .totals tr.grand td.val {{ background:#f1f5f9; font-weight:800; color:#0f172a; }}

  /* Transactions */
  .section-title {{ margin-top:28px; font-size:15px; font-weight:800; color:#0f172a; }}
  table.tx {{ width:100%; border-collapse:collapse; margin-top:10px; font-size:12px; }}
  table.tx thead th {{ background:#e5edf5; padding:9px 12px; border:1px solid #cbd5e1; color:#334155; text-align:center; font-weight:700; }}
  table.tx tbody td {{ padding:9px 12px; border:1px solid #e2e8f0; text-align:center; }}
  table.tx td.amt {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.tx tfoot td {{ padding:9px 12px; border:1px solid #e2e8f0; }}
  table.tx tfoot td.bal-lbl {{ text-align:right; font-weight:800; color:#0f172a; background:#f1f5f9; }}
  table.tx tfoot td.bal-val {{ background:#f1f5f9; font-weight:800; color:#0f172a; }}

  /* Bank panel */
  .bank-panel {{ margin-top:26px; background:#fffbeb; border:1px solid #fde68a; padding:14px 16px; }}
  .bank-row {{ display:flex; gap:16px; padding:4px 0; font-size:12px; }}
  .bank-name {{ font-weight:800; color:#0a2350; min-width:80px; }}
  .bank-num  {{ font-family: "SFMono-Regular", ui-monospace, Menlo, Consolas, monospace; color:#111; min-width:180px; }}
  .bank-holder {{ color:#78350f; }}
  .bank-note {{ font-size:11px; color:#78350f; margin-top:6px; }}

  /* Notes */
  .notes {{ margin-top:22px; font-size:11.5px; color:#475569; }}

  /* Footer */
  .foot {{ margin-top:26px; text-align:center; font-size:11px; color:#94a3b8; }}

  /* Print actions bar (HTML view only) */
  .actions {{ text-align:center; padding:16px 0 0 0; }}
  .actions button, .actions a.dl {{ display:inline-block; background:#0a2350; color:#fff; border:0; border-radius:99px; padding:8px 22px; font-weight:700; font-size:12px; cursor:pointer; text-decoration:none; margin: 0 6px; }}
  .actions a.dl {{ background:#f5b120; color:#0a2350; }}
  @media print {{ body {{ background:#fff }} .paper {{ box-shadow:none; margin:0 }} .actions {{ display:none }} }}
</style></head>
<body>
{actions_bar}
<div class="paper">
  {ribbon}

  <div class="head">
    <div class="logo"><img src="{logo_url}" alt="Intercloud Digital Inovasi"/></div>
    {COMPANY_HEADER_HTML}
  </div>

  <div class="titlebar">
    <h1>{header_title}</h1>
    <div class="meta-line">{title} Date: <b>{_long_date(issued_date)}</b></div>
    <div class="meta-line">{due_or_valid_label}: <b>{_long_date(due_or_valid_date)}</b></div>
  </div>

  <div class="to">
    <div class="lbl">Invoiced To</div>
    <div class="body">
      {_addressed_to_block(billed_to)}
    </div>
  </div>

  <table class="items">
    <thead>
      <tr><th style="text-align:center">Description</th><th style="text-align:center;width:180px">Total</th></tr>
    </thead>
    <tbody>{item_rows}</tbody>
  </table>

  <div class="totals">
    <table>
      <tr><td class="lbl">Sub Total</td><td class="val">{_idr(subtotal)}</td></tr>
      <tr><td class="lbl">Tax ({tax_percent:g}%)</td><td class="val">{_idr(tax_amount)}</td></tr>
      <tr><td class="lbl">Credit</td><td class="val">{credit_val}</td></tr>
      <tr class="grand"><td class="lbl">Total</td><td class="val">{_idr(total)}</td></tr>
      {amount_due_row}
    </table>
  </div>

  {cn_block}

  {tx_block}

  {bank_block}

  {("<div class='notes'>" + notes + "</div>") if notes else ""}

  {extra_footer}

  <div class="foot">PDF Generated on {generated_on}</div>
</div>
</body></html>
"""


def _render_pdf_bytes(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()


async def _invoice_document_html(db, d: dict, u: dict, for_pdf: bool) -> str:
    """Render HTML dokumen invoice (dipakai route documents + kirim ulang email)."""
    bank_doc = await db.settings.find_one({"key": "bank_accounts"}) or {}
    banks = bank_doc.get("value") or [
        {"bank": "MANDIRI", "number": "1240011911816", "holder": "INTERCLOUD DIGITAL INOVASI"},
        {"bank": "BCA", "number": "4730862038", "holder": "ANANG MADIA CUGITA"},
    ]

    status = (d.get("status") or "unpaid").lower()

    cn_docs = await db.credit_notes.find({"invoice_id": d["_id"], "status": "applied"}) \
        .sort("created_at", 1).to_list(50)
    credit_applied = sum(float(c.get("amount") or 0) for c in cn_docs)

    # Synthesize transactions from paid_at + payment_method when invoice is paid
    tx_list = list(d.get("transactions") or [])
    if not tx_list and status == "paid" and d.get("paid_at"):
        tx_list = [{
            "date": d.get("paid_at"),
            "gateway": (d.get("payment_method") or "Bank Transfer").replace("_", " ").title(),
            "transaction_id": d.get("payment_ref") or "",
            "amount": d.get("total", 0),
        }]

    return _pdf_template(
        doc_kind="invoice",
        number=d.get("number", ""),
        issued_date=(d.get("created_at") or "")[:10],
        due_or_valid_date=d.get("due_date", ""),
        due_or_valid_label="Due Date",
        items=d.get("items", []),
        subtotal=d.get("subtotal", 0),
        tax_amount=d.get("tax_amount", 0),
        total=d.get("total", 0),
        tax_percent=d.get("tax_percent", 11.0),
        credit_applied=credit_applied,
        credit_notes=cn_docs,
        status=status,
        billed_to=u,
        transactions=tx_list,
        banks=banks if status in ("unpaid", "overdue") else None,
        notes=d.get("notes", ""),
        for_pdf=for_pdf,
        logo_url=(await _get_branding_dict(db))["logo_dark"],
    )


@router.get("/documents/invoice/{iid}")
async def render_invoice_pdf(iid: str, format: str = "html", user=Depends(get_current_user)):
    db = await _get_db()
    d = await db.invoices.find_one({"_id": _oid(iid)})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # Access: owner or staff
    if user["role"] == "client" and str(d["user_id"]) != str(user["id"]):
        raise HTTPException(status_code=403, detail="Not your invoice")
    u = await db.users.find_one({"_id": d["user_id"]}) or {}

    html = await _invoice_document_html(db, d, u, for_pdf=(format == "pdf"))

    if format == "pdf":
        pdf_bytes = _render_pdf_bytes(html)
        filename = f"Invoice-{d.get('number','invoice')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # For HTML view, inject token so the "Download PDF" button in-page can carry auth
    token = user.get("_token", "")
    html = html.replace("{TOKEN_PLACEHOLDER}", token)
    return HTMLResponse(content=html)


@router.post("/admin/invoices/{iid}/resend-email")
async def admin_invoice_resend_email(iid: str, request: Request,
                                     staff=Depends(require_roles("admin", "finance", "support"))):
    """Kirim ulang email invoice ke klien dengan PDF invoice terlampir."""
    db = await _get_db()
    d = await db.invoices.find_one({"_id": _oid(iid)})
    if not d:
        raise HTTPException(status_code=404, detail="Invoice not found")
    u = await db.users.find_one({"_id": d["user_id"]})
    if not (u and u.get("email")):
        raise HTTPException(status_code=400, detail="Email klien tidak ditemukan")
    await _emails.ensure_pay_token(db, d)
    html = await _invoice_document_html(db, d, u, for_pdf=True)
    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf_bytes, html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membuat PDF: {type(e).__name__}: {e}")
    ctx = _emails.build_context(user=u, invoice=d)
    cc = _emails._cc_from_user(u)
    event_key = "payment_received" if d.get("status") == "paid" else "invoice_generated"
    result = await _emails.send_via_template(
        db, event_key=event_key, to_email=u["email"], ctx=ctx,
        invoice_id=str(d["_id"]), user_id=str(u["_id"]),
        attachments=[(f"Invoice-{d.get('number', 'invoice')}.pdf", pdf_bytes, "pdf")],
        cc_emails=cc)
    await log_audit(db, actor=staff, action="invoice.resend_email", category="billing",
                    target_type="invoice", target_id=iid, target_label=d.get("number", ""),
                    metadata={"to": u["email"], "delivery": result.get("status"),
                              "event_key": event_key}, request=request)
    return {"ok": result.get("status") == "sent", "to": u["email"], **result}


@router.get("/documents/quotation/{qid}")
async def render_quotation_pdf(qid: str, format: str = "html", staff=Depends(get_current_staff)):
    db = await _get_db()
    d = await db.quotations.find_one({"_id": _oid(qid), **_sales_scope_filter(staff, key="user_id")})
    if not d:
        raise HTTPException(status_code=404, detail="Quotation not found")
    u = await db.users.find_one({"_id": d["user_id"]}) or {}
    status = (d.get("status") or "draft").lower()

    html = _pdf_template(
        doc_kind="quotation",
        number=d.get("number", ""),
        issued_date=(d.get("created_at") or "")[:10],
        due_or_valid_date=d.get("valid_until", ""),
        due_or_valid_label="Valid Until",
        items=d.get("items", []),
        subtotal=d.get("subtotal", 0),
        tax_amount=d.get("tax_amount", 0),
        total=d.get("total", 0),
        tax_percent=d.get("tax_percent", 11.0),
        status=status,
        billed_to=u,
        transactions=[],
        banks=None,
        notes=d.get("notes", ""),
        extra_footer=(
            "<div style='margin-top:22px;font-size:11px;color:#64748b;line-height:1.7'>"
            "This quotation is valid until the date shown above. Prices are in Indonesian Rupiah (IDR) and exclude any applicable "
            "withholding tax. To accept this quotation, reply via email or WhatsApp - an invoice will be issued upon acceptance."
            "</div>"
        ),
        for_pdf=(format == "pdf"),
        logo_url=(await _get_branding_dict(db))["logo_dark"],
    )

    if format == "pdf":
        pdf_bytes = _render_pdf_bytes(html)
        filename = f"Quotation-{d.get('number','quotation')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    token = staff.get("_token", "")
    html = html.replace("{TOKEN_PLACEHOLDER}", token)
    return HTMLResponse(content=html)
