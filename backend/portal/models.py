"""Pydantic models for the portal."""
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import List, Optional, Literal
from datetime import datetime, timezone


# ---------- AUTH ----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str
    recaptcha_token: Optional[str] = None


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2)
    phone: Optional[str] = None
    company: Optional[str] = None
    # Optional billing address for immediate invoice-ready registration
    attention: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "Indonesia"
    npwp: Optional[str] = None
    # Optional lightweight CRM hints
    industry: Optional[str] = None
    accepts_tos: bool = True
    recaptcha_token: Optional[str] = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class AdminResetPasswordIn(BaseModel):
    new_password: str = Field(..., min_length=8)
    notify_user: bool = False


class FactoryResetIn(BaseModel):
    """Payload for POST /admin/system/factory-reset.

    - `admin_password`: current admin's password, re-entered for confirmation.
    - `confirm`: must equal the literal string "FACTORY RESET" — a second
      seatbelt on top of the password check so a leaked token alone can't
      wipe an install.
    """
    admin_password: str
    confirm: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr
    recaptcha_token: Optional[str] = None
class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: Literal["client", "admin", "sales", "support", "ticket_only"]
    company: Optional[str] = None
    phone: Optional[str] = None
    created_at: str
    assigned_client_ids: List[str] = []
    billing_emails: List[str] = []
    # Billing address (used on invoice/quotation PDFs)
    attention: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "Indonesia"
    npwp: Optional[str] = None
    # Fine-grained access control (staff only). If empty → role defaults apply.
    menu_keys: Optional[List[str]] = None      # allow-list of admin menu keys; None = use role default
    feature_flags: List[str] = []              # arbitrary per-user feature toggles
    is_active: bool = True


class LoginOut(BaseModel):
    token: str
    user: UserOut


# ---------- ADMIN: user mgmt ----------
class UserCreateIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["client", "admin", "sales", "support", "ticket_only"] = "client"
    company: Optional[str] = None
    phone: Optional[str] = None
    assigned_client_ids: List[str] = []
    billing_emails: List[str] = []
    attention: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = "Indonesia"
    npwp: Optional[str] = None
    menu_keys: Optional[List[str]] = None
    feature_flags: List[str] = []
    is_active: bool = True


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[Literal["client", "admin", "sales", "support", "ticket_only"]] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    assigned_client_ids: Optional[List[str]] = None
    billing_emails: Optional[List[str]] = None
    password: Optional[str] = None
    attention: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    npwp: Optional[str] = None
    menu_keys: Optional[List[str]] = None
    feature_flags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class BillingEmailsIn(BaseModel):
    billing_emails: List[EmailStr]


# ---------- PRODUCTS ----------
class ProductOption(BaseModel):
    """A single choice inside an option group (e.g., '4 GB RAM')."""
    label: str
    price_monthly_delta: float = 0
    price_setup_delta: float = 0
    is_default: bool = False


class ProductOptionGroup(BaseModel):
    """A configurable dimension on a product (e.g., 'RAM', 'CPU', 'OS').

    type='dropdown'   → user must pick exactly one option (radio behaviour)
    type='checkbox'   → user may pick 0..N options (e.g., add-on toggles inside a group)
    type='quantity'   → user picks an integer count, unit_price applies per unit
    """
    key: str                    # short identifier used inside order.config, e.g. 'ram'
    label: str                  # human label, e.g. 'RAM'
    type: Literal["dropdown", "checkbox", "quantity"] = "dropdown"
    required: bool = True
    options: List[ProductOption] = []
    # For type='quantity' only
    min_qty: int = 0
    max_qty: int = 100
    step_qty: int = 1
    unit_label: str = ""        # e.g. 'GB', 'core', 'IP'
    unit_price_monthly: float = 0
    unit_price_setup: float = 0


class ProductIn(BaseModel):
    name: str
    category: str               # now a free-form slug (see CategoryIn), no longer a Literal
    description: str = ""
    price_monthly: float
    setup_fee: float = 0
    billing_cycle: Literal["monthly", "quarterly", "semiannual", "annual"] = "monthly"
    features: List[str] = []
    is_active: bool = True
    # New — WHMCS-style configurable product
    is_addon: bool = False
    applies_to_product_ids: List[str] = []     # for add-ons: which base products this attaches to
    applies_to_categories: List[str] = []      # for add-ons: OR-attach to any product in these cats
    option_groups: List[ProductOptionGroup] = []
    stock_qty: Optional[int] = None            # None = unlimited
    sort_order: int = 100


class ProductOut(ProductIn):
    id: str
    created_at: str


# ---------- CATEGORIES ----------
class CategoryIn(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    label: str
    description: str = ""
    icon: str = ""             # lucide-react icon name (e.g., 'Server')
    sort_order: int = 100
    is_active: bool = True


class CategoryOut(CategoryIn):
    id: str
    created_at: str
    product_count: int = 0


# ---------- SERVICES (client-owned instances) ----------
class ServiceOut(BaseModel):
    id: str
    user_id: str
    product_id: str
    product_name: str
    category: str
    name: str
    status: Literal["active", "pending", "suspended", "terminated"]
    start_date: str
    next_renewal: str
    price_monthly: float
    config: dict = {}


class ServiceCreateIn(BaseModel):
    user_id: str
    product_id: str
    name: str
    status: Literal["active", "pending", "suspended", "terminated"] = "active"
    price_monthly: Optional[float] = None
    config: dict = {}


# ---------- ORDERS ----------
class OrderConfigSelection(BaseModel):
    """User's choice for one option-group on the base product."""
    group_key: str
    option_labels: List[str] = []   # for dropdown: exactly 1; for checkbox: 0..N
    quantity: Optional[int] = None  # for type='quantity'


class OrderIn(BaseModel):
    product_id: str
    notes: str = ""
    config: dict = {}                             # legacy free-form (kept for back-compat)
    selections: List[OrderConfigSelection] = []   # new — WHMCS-style option choices
    addon_ids: List[str] = []                     # attached add-on product IDs
    billing_cycle: Optional[str] = None           # optional override; else product default


class OrderPreviewOut(BaseModel):
    """Price breakdown returned by POST /orders/preview — used by the Review step."""
    base_line: dict
    option_lines: List[dict] = []
    addon_lines: List[dict] = []
    subtotal: float
    tax_percent: float
    tax_amount: float
    total: float
    setup_total: float


class OrderOut(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_email: str
    product_id: str
    product_name: str
    notes: str
    config: dict
    status: Literal["pending", "assigned", "provisioning", "active", "rejected"]
    assigned_admin_id: Optional[str] = None
    created_at: str


class OrderStatusUpdateIn(BaseModel):
    status: Literal[
        "pending_payment", "awaiting_verification", "awaiting_quote",
        "payment_verified", "assigned", "provisioning", "active", "rejected"
    ]


# ---------- INVOICES ----------
class InvoiceItem(BaseModel):
    description: str
    qty: int = 1
    unit_price: float
    total: float


class InvoiceIn(BaseModel):
    user_id: str
    items: List[InvoiceItem]
    tax_percent: float = 11.0
    due_date: str
    notes: str = ""


class InvoiceOut(BaseModel):
    id: str
    number: str
    user_id: str
    user_name: str
    user_email: str
    items: List[InvoiceItem]
    subtotal: float
    tax_amount: float
    total: float
    due_date: str
    status: Literal["unpaid", "paid", "overdue", "cancelled"]
    payment_method: Optional[str] = None
    paid_at: Optional[str] = None
    created_at: str
    notes: str = ""


class InvoiceStatusIn(BaseModel):
    status: Literal["unpaid", "paid", "overdue", "cancelled"]
    payment_method: Optional[str] = None


# ---------- QUOTATIONS ----------
class QuotationIn(BaseModel):
    user_id: str
    items: List[InvoiceItem]
    tax_percent: float = 11.0
    valid_until: str
    notes: str = ""


class QuotationOut(BaseModel):
    id: str
    number: str
    user_id: str
    user_name: str
    user_email: str
    items: List[InvoiceItem]
    subtotal: float
    tax_amount: float
    total: float
    valid_until: str
    status: Literal["draft", "sent", "accepted", "rejected", "expired"]
    created_at: str
    notes: str = ""


class QuotationStatusIn(BaseModel):
    status: Literal["draft", "sent", "accepted", "rejected", "expired"]


# ---------- EMAIL TEMPLATES ----------
EMAIL_EVENT_KEYS = Literal[
    "welcome",             # instant, on user register
    "order_confirmation",  # instant, on order created
    "invoice_generated",   # instant, on invoice created (D-14 baseline)
    "invoice_reminder_d3", # scheduled, 3 days before due
    "invoice_due",         # scheduled, on due date
    "invoice_overdue_d1",  # scheduled, 1 day past due
    "invoice_overdue_d3",  # scheduled, 3 days past due
    "invoice_overdue_d7",  # scheduled, 7 days past due
    "service_suspension",  # scheduled, D+8 past due
    "password_reset",      # instant, on forgot password
    "maintenance",         # on-demand blast
    "newsletter",          # on-demand blast
]


class EmailTemplateIn(BaseModel):
    event_key: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2)
    subject: str = Field(..., min_length=1)
    body_html: str
    # For invoice reminders: negative = before due date, positive = after due date.
    # For welcome/order/invoice_generated: null (fires instantly on event).
    offset_days: Optional[int] = None
    # Scheduled dispatch time-of-day in 24h HH:MM (UTC+7 Jakarta). Only meaningful
    # for time-triggered templates (D-3, D-day, D+1, D+3, D+7, D+8 suspension).
    send_time: Optional[str] = "08:00"
    # A template can be active/paused independently of the code path.
    is_active: bool = True
    # Freeform notes for the admin.
    notes: str = ""


class EmailTemplateOut(EmailTemplateIn):
    id: str
    updated_at: str
    created_at: str
    is_system: bool = False   # seeded templates cannot be deleted, only edited
    last_sent_at: Optional[str] = None
    send_count: int = 0


class EmailPreviewIn(BaseModel):
    """Render a template against a sample user/invoice/order context."""
    template_id: Optional[str] = None
    subject: Optional[str] = None
    body_html: Optional[str] = None
    # Pick a user/invoice/order to substitute variables against.
    sample_user_id: Optional[str] = None
    sample_invoice_id: Optional[str] = None
    sample_order_id: Optional[str] = None


class EmailSendTestIn(BaseModel):
    template_id: str
    to_email: EmailStr


class EmailNewsletterIn(BaseModel):
    """Send a one-off blast to a list of recipients (or all clients)."""
    subject: str
    body_html: str
    audience: Literal["all_clients", "all_users", "custom"] = "all_clients"
    to_emails: List[EmailStr] = []      # required when audience == 'custom'


class EmailLogOut(BaseModel):
    id: str
    event_key: str
    template_id: Optional[str] = None
    to_email: str
    subject: str
    status: Literal["queued", "sent", "failed", "skipped"]
    delivered_via: str = "smtp"
    error: Optional[str] = None
    sent_at: Optional[str] = None
    invoice_id: Optional[str] = None
    order_id: Optional[str] = None
    user_id: Optional[str] = None
    created_at: str


# ---------- ARTICLES / CMS ----------
class ArticleIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=240)
    slug: Optional[str] = None                # auto-generated from title if blank
    excerpt: str = Field("", max_length=500)
    body_html: str = ""
    cover_image_url: str = ""
    video_url: str = ""                       # optional embedded video (YouTube, Vimeo, direct MP4)
    author_name: str = ""
    tags: List[str] = []                      # normalised lowercase slugs
    category: str = ""                        # optional editorial category
    status: Literal["draft", "published", "archived"] = "draft"
    published_at: Optional[str] = None        # ISO date-time; auto-set on first publish
    # SEO
    meta_title: str = ""
    meta_description: str = ""
    meta_keywords: List[str] = []
    og_image_url: str = ""
    is_featured: bool = False


class ArticleOut(ArticleIn):
    id: str
    view_count: int = 0
    created_at: str
    updated_at: str


# ---------- TICKETS ----------
class TicketReplyIn(BaseModel):
    message: str


class TicketReply(BaseModel):
    author_id: str
    author_name: str
    author_role: str
    message: str
    created_at: str


class TicketIn(BaseModel):
    subject: str
    department: Literal["technical", "billing", "general", "sales"] = "technical"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    message: str


class TicketOut(BaseModel):
    id: str
    number: str
    user_id: str
    user_name: str
    user_email: str
    subject: str
    department: str
    priority: str
    status: Literal["open", "awaiting_client", "awaiting_staff", "resolved", "closed"]
    replies: List[TicketReply]
    created_at: str
    updated_at: str
