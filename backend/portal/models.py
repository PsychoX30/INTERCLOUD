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
    - `confirm`: must equal the literal string "FACTORY RESET" - a second
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
    role: Literal["client", "admin", "owner", "sales", "finance", "support", "ticket_only", "creative"]
    company: Optional[str] = None
    phone: Optional[str] = None
    created_at: str
    assigned_client_ids: List[str] = []
    twofa_enabled: bool = False
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
    must_change_password: bool = False         # forced password rotation (installer-seeded admin)


class LoginOut(BaseModel):
    token: Optional[str] = None
    user: Optional[UserOut] = None
    require_2fa: bool = False
    mfa_token: Optional[str] = None


# ---------- ADMIN: user mgmt ----------
class UserCreateIn(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: Literal["client", "admin", "owner", "sales", "finance", "support", "ticket_only", "creative"] = "client"
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
    role: Optional[Literal["client", "admin", "owner", "sales", "finance", "support", "ticket_only", "creative"]] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    assigned_client_ids: Optional[List[str]] = None
    billing_emails: Optional[List[EmailStr]] = None
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
    # Optional provisioning resource this option adds (vps/cloud)
    resource_kind: Optional[str] = None        # 'cores' | 'memory_mb' | 'disk_gb' | 'ip'
    resource_amount: float = 0


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
    # Optional: each unit of this quantity group adds this provisioning resource
    resource_kind: Optional[str] = None        # 'cores' | 'memory_mb' | 'disk_gb' | 'ip'
    resource_per_unit: float = 0


class ProductIn(BaseModel):
    name: str
    category: str               # now a free-form slug (see CategoryIn), no longer a Literal
    description: str = ""
    price_monthly: float
    setup_fee: float = 0
    billing_cycle: Literal["monthly", "quarterly", "semiannual", "annual"] = "monthly"
    features: List[str] = []
    is_active: bool = True
    # New - WHMCS-style configurable product
    is_addon: bool = False
    applies_to_product_ids: List[str] = []     # for add-ons: which base products this attaches to
    applies_to_categories: List[str] = []      # for add-ons: OR-attach to any product in these cats
    option_groups: List[ProductOptionGroup] = []
    provision: dict = {}                        # vps/cloud: {template_vmid, cores, memory_mb, disk_gb}
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
class HostingConfig(BaseModel):
    """Skema config layanan hosting (services.config untuk category=hosting)."""
    control_panel: Literal["cpanel", "plesk", "directadmin"] = "cpanel"
    domain: str = ""
    username: str = ""
    package: str = ""
    server_host: str = ""
    ip: str = ""
    provision_status: Literal["pending", "provisioned", "failed", "manual"] = "manual"
    provisioned_at: str = ""


class HostingProvisionIn(BaseModel):
    """Payload provisioning akun hosting via panel API."""
    control_panel: Literal["cpanel", "plesk", "directadmin"] = "cpanel"
    domain: str
    username: str = ""
    password: str = ""
    package: str = ""


class SelfServiceLogEntry(BaseModel):
    """Riwayat aksi mandiri klien pada layanan (start/stop/reboot/reset_password/upgrade)."""
    at: str
    action: str
    by: str


class PendingUpgrade(BaseModel):
    """Upgrade resource yang menunggu pembayaran invoice selisih."""
    cpu: int = 0
    ram_gb: int = 0
    disk_gb: int = 0
    monthly_delta: float = 0
    invoice_id: str
    requested_at: str


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
    self_service_log: List[SelfServiceLogEntry] = []
    pending_upgrade: Optional[PendingUpgrade] = None


class ServiceCreateIn(BaseModel):
    user_id: str
    product_id: str
    name: str
    status: Literal["active", "pending", "suspended", "terminated"] = "active"
    price_monthly: Optional[float] = None
    config: dict = {}


# ---------- DOMAINS (registrasi & manajemen domain) ----------
class DomainCheckIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253)


class DomainOrderIn(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    years: int = Field(default=1, ge=1, le=10)
    auto_renew: bool = True


class DomainRenewIn(BaseModel):
    years: int = Field(default=1, ge=1, le=10)


class DomainTransferIn(BaseModel):
    domain: str = Field(min_length=4, max_length=253)
    auth_code: str = Field(min_length=1, max_length=255)
    years: int = Field(default=1, ge=1, le=10)
    buy_whois_protection: bool = False


class DomainNameserversIn(BaseModel):
    nameservers: List[str] = Field(min_length=2, max_length=4)


# ---------- SSL (resale via RNA.id/RDASH) ----------
class SSLOrderIn(BaseModel):
    product_id: str
    period_months: int = Field(default=12, ge=1, le=36)
    domain: str = Field(min_length=4, max_length=253)
    dcv_method: Literal["dns", "http", "https", "email"] = "dns"
    dcv_email: Optional[str] = None
    csr_code: str = Field(min_length=10)


class SSLStatusIn(BaseModel):
    status: Literal["pending", "active", "failed", "cancelled"]


class DomainOut(BaseModel):
    id: str
    user_id: str
    user_name: str = ""
    domain: str
    tld: str
    status: Literal["pending", "active", "expiring", "expired", "cancelled"] = "pending"
    registrar: str = "rna"
    years: int = 1
    registered_at: Optional[str] = None
    expires_at: Optional[str] = None
    auto_renew: bool = True
    nameservers: List[str] = []
    price: float = 0
    invoice_id: Optional[str] = None
    order_ref: Optional[str] = None
    created_at: str = ""


class TicketStatusIn(BaseModel):
    status: Literal["open", "awaiting_client", "awaiting_staff", "resolved", "closed"]


# ---------- LEADS (lead-capture form landing page) ----------
class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(default="", max_length=32)
    company: str = Field(default="", max_length=120)
    need: str = Field(default="", max_length=120)          # layanan yang diminati
    message: str = Field(default="", max_length=2000)
    source: str = Field(default="landing", max_length=64)
    recaptcha_token: Optional[str] = None


class LeadStatusIn(BaseModel):
    status: Literal["new", "contacted", "qualified", "converted", "spam"]


class LeadOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str = ""
    company: str = ""
    need: str = ""
    message: str = ""
    source: str = "landing"
    status: Literal["new", "contacted", "qualified", "converted", "spam"] = "new"
    crm_id: Optional[str] = None
    created_at: str = ""


# ---------- NOC: DDoS / Netflow ----------
class ThresholdRuleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    metric: Literal["pps", "bps"] = "pps"
    threshold: float = Field(gt=0)
    window_s: int = Field(default=60, ge=10, le=3600)
    action: Literal["alert", "alert_blackhole"] = "alert"
    enabled: bool = True


class ThresholdRuleOut(ThresholdRuleIn):
    id: str
    created_at: str = ""


class NotifChannelIn(BaseModel):
    type: Literal["email", "whatsapp", "telegram", "webhook"]
    target: str = Field(min_length=3, max_length=300)
    events: List[str] = ["ddos"]
    enabled: bool = True


class NotifChannelOut(NotifChannelIn):
    id: str
    created_at: str = ""


class DDoSIncidentOut(BaseModel):
    id: str
    target: str
    attack_type: str = ""
    pps: float = 0
    bps: float = 0
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    status: Literal["active", "mitigated", "resolved", "false_positive"] = "active"
    action: str = "alert"
    rule_id: Optional[str] = None
    rule_name: str = ""
    started_at: str = ""
    ended_at: Optional[str] = None
    notified: List[str] = []


class DDoSIncidentStatusIn(BaseModel):
    status: Literal["active", "mitigated", "resolved", "false_positive"]


class BlackholeLogOut(BaseModel):
    id: str
    prefix: str
    action: Literal["add", "remove"]
    by: str = ""
    source: Literal["auto", "manual"] = "manual"
    device: str = ""
    at: str = ""


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
    selections: List[OrderConfigSelection] = []   # new - WHMCS-style option choices
    addon_ids: List[str] = []                     # attached add-on product IDs
    billing_cycle: Optional[str] = None           # optional override; else product default


class OrderPreviewOut(BaseModel):
    """Price breakdown returned by POST /orders/preview - used by the Review step."""
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
    tax_percent: Optional[float] = None
    tax_amount: float
    total: float
    due_date: str
    status: Literal["unpaid", "paid", "overdue", "cancelled"]
    payment_method: Optional[str] = None
    paid_at: Optional[str] = None
    payment_link: Optional[str] = None
    payment_ref: Optional[str] = None
    service_id: Optional[str] = None
    renewal_period: Optional[str] = None
    created_at: str
    notes: str = ""
    source_quotation_id: Optional[str] = None
    source_quotation_number: Optional[str] = None


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
    converted_invoice_id: Optional[str] = None
    converted_invoice_number: Optional[str] = None


class QuotationStatusIn(BaseModel):
    status: Literal["draft", "sent", "accepted", "rejected", "expired"]


class QuotationConvertIn(BaseModel):
    due_date: Optional[str] = None


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
    cover_image_alt: str = ""                 # descriptive alt text for the hero image (SEO + a11y)
    video_url: str = ""                       # optional embedded video (YouTube, Vimeo, direct MP4)
    author_name: str = ""
    tags: List[str] = []                      # normalised lowercase slugs
    category: str = ""                        # optional editorial category
    type: Literal["blog", "kb"] = "blog"      # blog = public marketing articles; kb = client-facing knowledge base
    kb_section: str = ""                      # optional grouping for KB articles (e.g. "Billing", "Layanan")
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


# ---------- TRANSACTION LEDGER ----------
class TransactionIn(BaseModel):
    """Manual ledger entry. Auto-populated entries from invoice events omit this."""
    invoice_id: Optional[str] = None
    user_id: Optional[str] = None
    customer_name: str = ""
    amount: float = 0.0
    method: Optional[str] = None       # bank_transfer | duitku | xendit | credit_note | manual
    status: Literal["pending", "paid", "unpaid", "failed", "refunded", "cancelled"] = "paid"
    paid_at: Optional[str] = None      # ISO datetime string
    verified_at: Optional[str] = None  # ISO datetime string
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    reference: Optional[str] = None
    notes: str = ""


class TransactionOut(BaseModel):
    id: str
    invoice_id: Optional[str] = None
    invoice_number: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    customer_name: str = ""
    amount: float
    method: Optional[str] = None
    status: str
    paid_at: Optional[str] = None
    verified: bool = False
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    reference: Optional[str] = None
    notes: str = ""
    source: Literal["auto", "manual"] = "auto"
    created_at: str
    updated_at: str


class TransactionVerifyIn(BaseModel):
    notes: str = ""


# ---------- SLA ----------
class SLAIncidentIn(BaseModel):
    service_id: Optional[str] = None
    device_id: Optional[str] = None
    title: str = Field(..., min_length=2)
    description: str = ""
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    started_at: str  # ISO datetime
    ended_at: Optional[str] = None
    affected_customers: List[str] = []  # user_id list
    status: Literal["open", "resolved", "postmortem"] = "open"
    root_cause: str = ""
    created_by: Optional[str] = None
    notes: str = ""


class SLAIncidentOut(SLAIncidentIn):
    id: str
    duration_minutes: Optional[int] = None
    created_at: str
    updated_at: str


class SLAIncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[Literal["critical", "high", "medium", "low"]] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    affected_customers: Optional[List[str]] = None
    status: Optional[Literal["open", "resolved", "postmortem"]] = None
    root_cause: Optional[str] = None
    notes: Optional[str] = None


class SLAConfigIn(BaseModel):
    sla_target_uptime_percent: float = Field(..., ge=0, le=100)
    sla_excluded_maintenance_windows: List[str] = []  # cron-like strings or human-readable
    auto_create_sla_incidents: bool = False


class SLAConfigOut(SLAConfigIn):
    id: str = "sla_config"
    updated_at: str


# ---------- SETTINGS (generic) ----------
class SettingIn(BaseModel):
    key: str = Field(..., min_length=1)
    value: str


class SettingOut(SettingIn):
    id: str
    updated_at: str


# ---------- TICKETS ----------
class TicketReplyIn(BaseModel):
    message: str
    internal: bool = False


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
    related_device_id: Optional[str] = None   # optional link to a mikrotik_devices row


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
    related_device_id: Optional[str] = None
    related_device_name: Optional[str] = None
    created_at: str
    updated_at: str
