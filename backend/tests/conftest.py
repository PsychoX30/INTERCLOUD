"""Shared pytest configuration — loads env vars from /app/backend/.env if not already set."""
import os
import sys
from pathlib import Path

# Allow `from portal import …` imports regardless of pytest rootdir resolution.
sys.path.insert(0, "/app/backend")


def _load_env_from_file() -> None:
    env_path = Path("/app/backend/.env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


_load_env_from_file()

# Legacy suites default to the local backend: it is rate-limit isolated via
# the per-test X-Forwarded-For injection below. Full e2e through the public
# ingress is covered separately by the platform testing agent.
if not os.environ.get("PORTAL_API_BASE"):
    os.environ["PORTAL_API_BASE"] = "http://127.0.0.1:8001/api/portal"


# ------------------------------------------------------------------
# Demo fixture users — legacy suites (test_portal.py, …) expect staff/client
# accounts that portal/seed.py intentionally no longer creates. Create them
# here through the admin API instead (robust to future seed changes).
# ------------------------------------------------------------------
_DEMO_USERS = [
    {"email": "demo@client.com", "password": "ClientDemo2026!", "name": "Demo Client",
     "role": "client", "company": "PT Contoh Digital",
     "billing_emails": ["finance@contoh-digital.co.id"],
     "attention": "Finance Dept", "address_line1": "Jl. Contoh No. 1",
     "city": "Jakarta Selatan", "province": "DKI Jakarta",
     "postal_code": "12190", "country": "Indonesia", "npwp": "01.234.567.8-901.000"},
    {"email": "sales@intercloud-digital.com", "password": "Sales2026!",
     "name": "Sales Person", "role": "sales"},
    {"email": "support@intercloud-digital.com", "password": "Support2026!",
     "name": "Support Team", "role": "support"},
    {"email": "ticket@intercloud-digital.com", "password": "Ticket2026!",
     "name": "Ticket Agent", "role": "ticket_only"},
]


def _ensure_demo_users_impl() -> None:
    import requests
    base = "http://127.0.0.1:8001/api/portal"
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@intercloud-digital.com")
    admin_pw = os.environ.get("ADMIN_PASSWORD", "AdminIntercloud2026!")
    try:
        r = requests.post(f"{base}/auth/login",
                          json={"email": admin_email, "password": admin_pw}, timeout=15)
        tok = (r.json() or {}).get("token")
    except Exception:
        return
    if not tok:
        return
    h = {"Authorization": f"Bearer {tok}"}
    listing = {}
    try:
        rows = requests.get(f"{base}/admin/users", headers=h, timeout=15).json()
        listing = {u.get("email"): u.get("id") for u in rows if isinstance(u, dict)}
    except Exception:
        pass
    for u in _DEMO_USERS:
        try:
            if u["email"] in listing:
                # Re-sync full profile in case an older run drifted
                requests.put(f"{base}/admin/users/{listing[u['email']]}",
                             json={k: v for k, v in u.items() if k != "email"},
                             headers=h, timeout=15)
            else:
                requests.post(f"{base}/admin/users", json=u, headers=h, timeout=15)
        except Exception:
            pass
    _ensure_demo_dataset(base, h)


def _ensure_demo_dataset(base: str, h: dict) -> None:
    """Idempotent demo dataset the legacy suites assert against:
    products (vps/hosting/colocation), 3 services + 3 invoices
    (overdue/unpaid/paid) + 1 open ticket for demo@client.com, and the
    demo client assigned to the sales rep."""
    import requests
    try:
        users = requests.get(f"{base}/admin/users", headers=h, timeout=15).json()
        by_email = {u.get("email"): u for u in users if isinstance(u, dict)}
        client = by_email.get("demo@client.com")
        sales = by_email.get("sales@intercloud-digital.com")
        if not client:
            return
        cid = client["id"]
        # Sales rep must have the demo client assigned
        if sales is not None and cid not in (sales.get("assigned_client_ids") or []):
            requests.put(f"{base}/admin/users/{sales['id']}",
                         json={"assigned_client_ids": [cid]}, headers=h, timeout=15)
        # Products per category
        prods = requests.get(f"{base}/admin/products", headers=h, timeout=15).json()
        by_cat = {}
        for p in prods:
            by_cat.setdefault(p.get("category"), p)
        for cat, name, price in (("vps", "Fixture VPS S", 350000),
                                 ("hosting", "Fixture Hosting Basic", 150000),
                                 ("colocation", "Fixture Colo 1U", 1500000)):
            if cat not in by_cat:
                r = requests.post(f"{base}/admin/products", headers=h, timeout=15,
                                  json={"name": name, "category": cat,
                                        "description": "fixture", "price_monthly": price})
                if r.status_code == 200:
                    by_cat[cat] = r.json()
        # SLA regression fixture product (test_sla_products.py)
        if not any(p.get("name") == "DC-to-DC 100 Mbps" for p in prods):
            requests.post(f"{base}/admin/products", headers=h, timeout=15,
                          json={"name": "DC-to-DC 100 Mbps", "category": "connectivity",
                                "description": "Point-to-point DC interconnect",
                                "price_monthly": 4500000,
                                "features": ["100 Mbps dedicated", "SLA 99.5% uptime",
                                              "24/7 NOC support"]})
        # Services (vps/hosting/colocation) for the demo client
        svcs = requests.get(f"{base}/admin/services", headers=h, timeout=15).json()
        have_cats = {s.get("category") for s in svcs if s.get("user_id") == cid}
        for cat in ("vps", "hosting", "colocation"):
            if cat not in have_cats and by_cat.get(cat):
                requests.post(f"{base}/admin/services", headers=h, timeout=15,
                              json={"user_id": cid, "product_id": by_cat[cat]["id"],
                                    "name": f"fixture-{cat}", "status": "active",
                                    "config": {}})
        # Invoices: one overdue (1.665.000), one unpaid, one paid
        invs = requests.get(f"{base}/admin/invoices", headers=h, timeout=15).json()
        cli_st = {i.get("status") for i in invs if i.get("user_id") == cid}
        def _mk_invoice(amount, due, status=None):
            r = requests.post(f"{base}/admin/invoices", headers=h, timeout=15,
                              json={"user_id": cid, "due_date": due, "tax_percent": 11,
                                    "notes": "fixture",
                                    "items": [{"description": "Fixture line", "qty": 1,
                                               "unit_price": amount, "total": amount}]})
            if r.status_code == 200 and status:
                requests.put(f"{base}/admin/invoices/{r.json()['id']}/status",
                             headers=h, timeout=15, json={"status": status})
        if "overdue" not in cli_st:
            _mk_invoice(1500000, "2025-01-31", "overdue")   # 1.5jt + 11% = 1.665.000
        if "unpaid" not in cli_st:
            _mk_invoice(250000, "2030-12-31")
        if "paid" not in cli_st:
            _mk_invoice(100000, "2030-12-31", "paid")
        # Open ticket from the client
        cl = requests.post(f"{base}/auth/login", timeout=15,
                           json={"email": "demo@client.com", "password": "ClientDemo2026!"})
        ctok = (cl.json() or {}).get("token")
        if ctok:
            ch = {"Authorization": f"Bearer {ctok}"}
            tk = requests.get(f"{base}/client/tickets", headers=ch, timeout=15).json()
            if not any(t.get("status") in ("open", "awaiting_staff") for t in tk):
                requests.post(f"{base}/client/tickets", headers=ch, timeout=15,
                              json={"subject": "Fixture ticket", "department": "technical",
                                    "priority": "medium", "message": "fixture"})
            # At least one order so CRM enrichment for this client is stable
            existing_orders = requests.get(f"{base}/client/orders", headers=ch, timeout=15).json()
            if not existing_orders and by_cat.get("vps"):
                requests.post(f"{base}/client/orders", headers=ch, timeout=15,
                              json={"product_id": by_cat["vps"]["id"],
                                    "notes": "fixture order", "config": {}})
        # Demo articles the article suites assert against
        _ensure_demo_articles(base, h)
    except Exception:
        pass


_DEMO_ARTICLES = [
    {"title": "Colocation vs Dedicated vs VPS", "slug": "colocation-vs-dedicated-vs-vps",
     "excerpt": "Choosing the right infrastructure for your workload.",
     "body_html": "<p>Colocation, dedicated servers, and VPS each fit different workloads.</p>",
     "tags": ["guide", "colocation"], "category": "guide", "status": "published"},
    {"title": "Cyber 1 Core Network Upgrade Notice", "slug": "cyber-1-core-network-upgrade-notice",
     "excerpt": "Scheduled maintenance window for the Cyber 1 core network.",
     "body_html": "<p>Maintenance notice.</p>",
     "tags": ["announcement"], "category": "announcement", "status": "published"},
    {"title": "Why Indonesian Enterprises Move to Local Cloud",
     "slug": "why-indonesian-enterprises-move-local-cloud",
     "excerpt": "Latency, sovereignty, and cost drive the local cloud shift.",
     "body_html": "<p>Local cloud adoption is accelerating.</p>",
     "tags": ["guide", "cloud"], "category": "guide", "status": "published"},
]


def _ensure_demo_articles(base: str, h: dict) -> None:
    import requests
    existing = requests.get(f"{base}/admin/articles", headers=h, timeout=15).json()
    rows = existing if isinstance(existing, list) else existing.get("results", [])
    have = {a.get("slug") for a in rows}
    for a in _DEMO_ARTICLES:
        if a["slug"] not in have:
            requests.post(f"{base}/admin/articles", json=a, headers=h, timeout=15)


_demo_users_done = False


# ------------------------------------------------------------------
# Per-test rate-limit isolation.
# The login limiter keys by client IP (X-Forwarded-For aware). When the whole
# suite runs in parallel, hundreds of logins from one IP trip the 10/min
# limit and drown the run in spurious 429s. Give every test its own private
# IP in the 10.99.0.0/16 test range for DIRECT backend calls only (the
# production path through nginx/ingress overrides XFF, so this cannot be
# abused externally).
# ------------------------------------------------------------------
import itertools as _it
import requests as _rq

_orig_session_request = _rq.sessions.Session.request


def _public_base() -> str:
    url = os.environ.get("REACT_APP_BACKEND_URL", "")
    if not url:
        try:
            for line in Path("/app/frontend/.env").read_text().splitlines():
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip().strip('"')
                    break
        except Exception:
            url = ""
    return url.rstrip("/")


_PUBLIC_BASE = _public_base()


def _test_ip() -> str:
    """Deterministic per-test IP derived from PYTEST_CURRENT_TEST (set by
    pytest during setup/call/teardown) + worker PID. Session fixtures run in
    the context of the first requesting test, so their logins share that
    test's bucket only."""
    import hashlib
    cur = os.environ.get("PYTEST_CURRENT_TEST", "")
    h = int(hashlib.md5(f"{os.getpid()}::{cur.split(' ')[0]}".encode()).hexdigest()[:6], 16)
    return f"10.{(h >> 16) % 200 + 10}.{(h >> 8) % 256}.{h % 254 + 1}"


def _xff_patched_request(self, method, url, **kwargs):
    # Route API calls that target the public preview URL straight to the local
    # backend: functionally identical, but each test then gets its own
    # rate-limit bucket via the X-Forwarded-For injection below. Full
    # through-the-ingress e2e is covered by the platform testing agent.
    if _PUBLIC_BASE and isinstance(url, str) and url.startswith(_PUBLIC_BASE + "/api"):
        url = "http://127.0.0.1:8001" + url[len(_PUBLIC_BASE):]
    if isinstance(url, str) and ("127.0.0.1:8001" in url or "localhost:8001" in url):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("X-Forwarded-For", _test_ip())
        kwargs["headers"] = headers
        if str(method).upper() == "GET":
            # GETs are idempotent — absorb transient stalls (e.g. while the
            # backup/restore suite briefly holds Mongo) with one retry.
            try:
                return _orig_session_request(self, method, url, **kwargs)
            except (_rq.exceptions.Timeout, _rq.exceptions.ConnectionError):
                import time as _time
                _time.sleep(2)
                kwargs["timeout"] = max(45, kwargs.get("timeout") or 0)
                return _orig_session_request(self, method, url, **kwargs)
    return _orig_session_request(self, method, url, **kwargs)


_rq.sessions.Session.request = _xff_patched_request


# ------------------------------------------------------------------
# Mail suites toggle GLOBAL integration state (SMTP/IMAP enabled flags).
# Under xdist parallelism two mail modules can race each other's toggles —
# serialize them with a cross-process file lock (whole module = one holder).
# ------------------------------------------------------------------
import pytest  # noqa: E402

_MAIL_MODULE_KEYS = ("mail", "imap", "iter29", "iter30", "test_emails",
                     "integrations_unified", "email_refresh",
                     "landing_cms_and_backup", "system_update",
                     "login_analytics", "security_whitelist",
                     "csp_report", "phase_optimization", "mikrotik_devices",
                     "recaptcha", "duitku_payment_flow")


@pytest.fixture(scope="module", autouse=True)
def _serialize_shared_mail_state(request):
    name = getattr(request.module, "__name__", "")
    if not any(k in name for k in _MAIL_MODULE_KEYS):
        yield
        return
    import fcntl
    f = open("/tmp/ic_mail_suite.lock", "w")
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def pytest_sessionstart(session):
    global _demo_users_done
    # xdist: only the first worker (or a non-distributed run) seeds fixtures;
    # the data is idempotent and long-lived, so other workers just reuse it.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker not in (None, "gw0"):
        return
    if not _demo_users_done:
        _ensure_demo_users_impl()
        _demo_users_done = True
