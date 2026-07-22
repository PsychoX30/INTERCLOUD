"""Idempotent seed: demo admin, demo client, sample products/services/invoices/tickets."""
import os
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from .auth import hash_password, verify_password


async def seed_all(db):
    await _seed_users(db)
    await _seed_products(db)
    await _seed_client_data(db)
    await _seed_articles(db)
    await _migrate_assets_straight_line(db)
    await _write_credentials_file(db)


async def _migrate_assets_straight_line(db):
    """One-shot backfill: ensure every asset doc has `salvage_value` and
    `useful_life_years` fields so the straight-line depreciation formula
    can be applied without falling back to legacy heuristics on every read.

    Legacy fallback:
      - useful_life_years derived from useful_life_months (÷12, rounded)
      - useful_life_years derived from depreciation_percent (100 ÷ pct, rounded)
    Salvage defaults to 0 when missing.
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


async def _seed_users(db):
    admin_email = os.environ["ADMIN_EMAIL"].lower()
    admin_pw = os.environ["ADMIN_PASSWORD"]
    client_email = os.environ["CLIENT_EMAIL"].lower()
    client_pw = os.environ["CLIENT_PASSWORD"]

    # Admin
    a = await db.users.find_one({"email": admin_email})
    if not a:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_pw),
            "name": "Intercloud Admin",
            "role": "admin",
            "company": "PT Intercloud Digital Inovasi",
            "phone": "+62 878-1239-7187",
            "assigned_client_ids": [],
            "billing_emails": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif not verify_password(admin_pw, a["password_hash"]):
        await db.users.update_one(
            {"_id": a["_id"]},
            {"$set": {"password_hash": hash_password(admin_pw)}},
        )

    # Client (with example additional billing recipient)
    c = await db.users.find_one({"email": client_email})
    if not c:
        await db.users.insert_one({
            "email": client_email,
            "password_hash": hash_password(client_pw),
            "name": "Budi Santoso",
            "role": "client",
            "company": "PT Contoh Digital",
            "phone": "+62 812-3456-7890",
            "assigned_client_ids": [],
            "billing_emails": ["finance@contoh-digital.co.id"],
            "attention": "Budi Santoso",
            "address_line1": "Jl. Sudirman Kav. 52-53",
            "address_line2": "SCBD Tower 1, Lantai 8",
            "city": "Jakarta Selatan",
            "province": "DKI Jakarta",
            "postal_code": "12190",
            "country": "Indonesia",
            "npwp": "01.234.567.8-901.000",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        upd = {}
        if not verify_password(client_pw, c["password_hash"]):
            upd["password_hash"] = hash_password(client_pw)
        # Backfill billing_emails for pre-existing seed
        if not c.get("billing_emails"):
            upd["billing_emails"] = ["finance@contoh-digital.co.id"]
        # Backfill billing address for pre-existing seed
        if not c.get("address_line1"):
            upd.update({
                "attention": "Budi Santoso",
                "address_line1": "Jl. Sudirman Kav. 52-53",
                "address_line2": "SCBD Tower 1, Lantai 8",
                "city": "Jakarta Selatan",
                "province": "DKI Jakarta",
                "postal_code": "12190",
                "country": "Indonesia",
                "npwp": "01.234.567.8-901.000",
            })
        if upd:
            await db.users.update_one({"_id": c["_id"]}, {"$set": upd})

    # Staff demos (sales / support / ticket_only)
    staff_seeds = [
        {"email": "sales@intercloud-digital.com", "password": "Sales2026!", "name": "Sales Officer",
         "role": "sales", "phone": "+62 811-1111-1111"},
        {"email": "support@intercloud-digital.com", "password": "Support2026!", "name": "Support Engineer",
         "role": "support", "phone": "+62 811-2222-2222"},
        {"email": "ticket@intercloud-digital.com", "password": "Ticket2026!", "name": "Ticket Agent",
         "role": "ticket_only", "phone": "+62 811-3333-3333"},
    ]
    for s in staff_seeds:
        existing = await db.users.find_one({"email": s["email"]})
        if not existing:
            await db.users.insert_one({
                "email": s["email"],
                "password_hash": hash_password(s["password"]),
                "name": s["name"],
                "role": s["role"],
                "company": "PT Intercloud Digital Inovasi",
                "phone": s["phone"],
                "assigned_client_ids": [],
                "billing_emails": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        elif not verify_password(s["password"], existing["password_hash"]):
            await db.users.update_one(
                {"_id": existing["_id"]},
                {"$set": {"password_hash": hash_password(s["password"])}},
            )

    # Wire the sales user to the demo client for scoping demonstration
    sales_user = await db.users.find_one({"email": "sales@intercloud-digital.com"})
    demo_client = await db.users.find_one({"email": client_email})
    if sales_user and demo_client:
        await db.users.update_one(
            {"_id": sales_user["_id"]},
            {"$set": {"assigned_client_ids": [demo_client["_id"]]}},
        )


PRODUCTS_SEED = [
    {"name": "Web Hosting Starter", "category": "hosting", "price_monthly": 25_000, "setup_fee": 0,
     "description": "cPanel hosting with NVMe SSD, ideal for company websites & blogs.",
     "features": ["5 GB NVMe Storage", "Unmetered Bandwidth", "5 Email Accounts", "Free SSL", "LiteSpeed Web Server"]},
    {"name": "Web Hosting Business", "category": "hosting", "price_monthly": 75_000, "setup_fee": 0,
     "description": "cPanel hosting for mid-traffic sites & small e-commerce.",
     "features": ["25 GB NVMe Storage", "Unmetered Bandwidth", "Unlimited Email", "Free SSL", "Daily Backup"]},
    {"name": "VPS KVM 2GB", "category": "vps", "price_monthly": 150_000, "setup_fee": 0,
     "description": "KVM full-root VPS, ideal for dev environments and API backends.",
     "features": ["2 vCPU", "2 GB RAM", "40 GB NVMe", "2 TB Bandwidth", "1 Gbps Port"]},
    {"name": "VPS KVM 4GB", "category": "vps", "price_monthly": 300_000, "setup_fee": 0,
     "description": "KVM full-root VPS for production apps.",
     "features": ["4 vCPU", "4 GB RAM", "80 GB NVMe", "4 TB Bandwidth", "1 Gbps Port"]},
    {"name": "Dedicated Server 16 Core", "category": "dedicated", "price_monthly": 3_500_000, "setup_fee": 500_000,
     "description": "Bare-metal server with dedicated resources.",
     "features": ["16 Core Xeon", "64 GB RAM", "2 TB NVMe", "10 TB Bandwidth", "IPMI Access"]},
    {"name": "Colocation 1U", "category": "colocation", "price_monthly": 1_500_000, "setup_fee": 500_000,
     "description": "House your 1U server in a Tier III data center.",
     "features": ["1U Rack Space", "N+1 Power", "100 Mbps Port", "24/7 DC Access", "Free Remote Hands (2 hr/mo)"]},
    {"name": "Cloud Instance Small", "category": "cloud", "price_monthly": 250_000, "setup_fee": 0,
     "description": "Auto-scale cloud instance with hybrid options.",
     "features": ["2 vCPU", "2 GB RAM", "40 GB SSD", "Hourly Billing", "Snapshot & Auto Backup"]},
    {"name": "Firewall Solution", "category": "firewall", "price_monthly": 0, "setup_fee": 0,
     "description": "FortiGate / pfSense / Palo Alto managed firewall (custom quote).",
     "features": ["Managed 24/7", "IPS/IDS", "SSL VPN", "Multi-WAN", "Content Filtering"]},
    {"name": "DC-to-DC 100 Mbps", "category": "interconnect", "price_monthly": 5_500_000, "setup_fee": 1_000_000,
     "description": "Layer-2 interconnect between Jakarta data centers.",
     "features": ["100 Mbps Symmetric", "Layer 2 Ethernet", "Sub-1ms latency", "Redundant Path", "99.5% SLA"]},
]


async def _seed_products(db):
    for p in PRODUCTS_SEED:
        exists = await db.products.find_one({"name": p["name"]})
        if not exists:
            await db.products.insert_one({
                **p,
                "is_active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    # Idempotent SLA drift correction — replaces stale 99.9%/99.95%/99.99%
    # references left over from earlier seed versions with the canonical 99.5%.
    async for doc in db.products.find({}):
        feats = doc.get("features") or []
        new_feats = []
        changed = False
        for f in feats:
            if not isinstance(f, str):
                new_feats.append(f)
                continue
            nf = (f.replace("99.99%", "99.5%")
                   .replace("99.95%", "99.5%")
                   .replace("99.9%", "99.5%")
                   .replace("99,99%", "99,5%")
                   .replace("99,95%", "99,5%")
                   .replace("99,9%", "99,5%"))
            if nf != f:
                changed = True
            new_feats.append(nf)
        if changed:
            await db.products.update_one({"_id": doc["_id"]}, {"$set": {"features": new_feats}})


async def _seed_client_data(db):
    client = await db.users.find_one({"email": os.environ["CLIENT_EMAIL"].lower()})
    if not client:
        return
    cid = client["_id"]

    now = datetime.now(timezone.utc)

    # Services
    if await db.services.count_documents({"user_id": cid}) == 0:
        vps = await db.products.find_one({"name": "VPS KVM 4GB"})
        host = await db.products.find_one({"name": "Web Hosting Business"})
        colo = await db.products.find_one({"name": "Colocation 1U"})
        seeds = [
            (vps, "vps-prod-01", "active", 30),
            (host, "hosting-marketing", "active", 15),
            (colo, "colo-cyber1-1u", "active", 45),
        ]
        for prod, sname, status, start_days_ago in seeds:
            if not prod:
                continue
            start = now - timedelta(days=start_days_ago)
            await db.services.insert_one({
                "user_id": cid,
                "product_id": prod["_id"],
                "product_name": prod["name"],
                "category": prod["category"],
                "name": sname,
                "status": status,
                "start_date": start.date().isoformat(),
                "next_renewal": (start + timedelta(days=30)).date().isoformat(),
                "price_monthly": prod["price_monthly"],
                "config": {
                    "ip": "103.28.14." + str(hash(sname) % 240 + 10),
                    "hostname": f"{sname}.icd-cust.net",
                    "os": "Ubuntu 22.04" if prod["category"] == "vps" else "-",
                    "control_panel": "cPanel/WHM" if prod["category"] == "hosting" else "-",
                    "node": "PROX-JKT-05" if prod["category"] == "vps" else "-",
                    "rack": "Rack-B12-U34" if prod["category"] == "colocation" else "-",
                },
                "created_at": start.isoformat(),
            })

    # Invoices — 3 samples: 1 paid, 1 unpaid due-soon, 1 overdue
    if await db.invoices.count_documents({"user_id": cid}) == 0:
        seeds = [
            {"days_ago": 30, "days_due": -15, "status": "paid", "amount_hint": 300_000,
             "desc": "VPS KVM 4GB — Renewal"},
            {"days_ago": 5, "days_due": 8, "status": "unpaid", "amount_hint": 75_000,
             "desc": "Web Hosting Business — Renewal"},
            {"days_ago": 40, "days_due": -10, "status": "overdue", "amount_hint": 1_500_000,
             "desc": "Colocation 1U — Renewal"},
        ]
        year = now.year
        for i, s in enumerate(seeds, start=1):
            created = now - timedelta(days=s["days_ago"])
            due = now + timedelta(days=s["days_due"])
            subtotal = s["amount_hint"]
            tax = round(subtotal * 0.11, 2)
            total = round(subtotal + tax, 2)
            doc = {
                "number": f"INV-{year}-{i:05d}",
                "user_id": cid,
                "items": [{"description": s["desc"], "qty": 1, "unit_price": subtotal, "total": subtotal}],
                "subtotal": subtotal,
                "tax_percent": 11,
                "tax_amount": tax,
                "total": total,
                "due_date": due.date().isoformat(),
                "status": s["status"],
                "payment_method": "bank_transfer" if s["status"] == "paid" else None,
                "paid_at": (created + timedelta(days=3)).isoformat() if s["status"] == "paid" else None,
                "notes": "",
                "created_at": created.isoformat(),
            }
            await db.invoices.insert_one(doc)

    # Ticket
    if await db.tickets.count_documents({"user_id": cid}) == 0:
        now_iso = now.isoformat()
        await db.tickets.insert_one({
            "number": f"TCK-{now.year}-00001",
            "user_id": cid,
            "subject": "Request rDNS untuk IP 103.28.14.42",
            "department": "technical",
            "priority": "medium",
            "status": "awaiting_staff",
            "replies": [
                {
                    "author_id": str(cid),
                    "author_name": client["name"],
                    "author_role": "client",
                    "message": "Halo tim, mohon bantuan set rDNS untuk IP 103.28.14.42 ke mail.contoh-digital.com. Terima kasih.",
                    "created_at": now_iso,
                }
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
        })

    # CRM mirror row for the demo client (idempotent)
    if not await db.crm_customers.find_one({"email": client["email"]}):
        now_iso = now.isoformat()
        await db.crm_customers.insert_one({
            "name": client["name"],
            "email": client["email"],
            "phone": client.get("phone", ""),
            "company": client.get("company", ""),
            "position": "",
            "industry": "Digital / Media",
            "status": "existing",
            "notes": "Seeded demo client — mirrors the portal user.",
            "user_id": cid,
            "source": "seed",
            "created_at": now_iso,
            "updated_at": now_iso,
        })


async def _write_credentials_file(db):
    """Persist demo credentials for the testing agent."""
    path = "/app/memory/test_credentials.md"
    admin_email = os.environ["ADMIN_EMAIL"]
    admin_pw = os.environ["ADMIN_PASSWORD"]
    client_email = os.environ["CLIENT_EMAIL"]
    client_pw = os.environ["CLIENT_PASSWORD"]
    content = f"""# Intercloud Portal — Test Credentials

## Admin
- Email: `{admin_email}`
- Password: `{admin_pw}`
- Role: admin
- Login URL: `/portal/login` → redirects to `/portal/admin/dashboard`

## Client (demo)
- Email: `{client_email}`
- Password: `{client_pw}`
- Role: client
- Login URL: `/portal/login` → redirects to `/portal/client/dashboard`

## Auth endpoints
- `POST /api/portal/auth/login` → returns `{{token, user}}`
- `GET  /api/portal/auth/me` → Bearer token in Authorization header
- `POST /api/portal/admin/users` → admin-only, creates client/admin

## Sample seeded data (for client demo)
- 3 active services (VPS, Hosting, Colocation)
- 3 invoices (1 paid, 1 unpaid, 1 overdue)
- 1 open ticket

Any changes must keep this file up to date.
"""
    try:
        import os as _os
        _os.makedirs("/app/memory", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
    except Exception:
        pass


async def _seed_articles(db):
    """Insert a handful of demo articles once. Idempotent by slug."""
    now = datetime.now(timezone.utc).isoformat()
    demos = [
        {
            "title": "Why Indonesian enterprises are moving workloads to local cloud",
            "slug": "why-indonesian-enterprises-move-local-cloud",
            "excerpt": "Data sovereignty, latency, and cost are reshaping how Indonesian businesses choose infrastructure. Here's what we've learned from 300+ migrations.",
            "body_html": (
                "<p>Over the past three years, PT Intercloud Digital Inovasi has migrated more than "
                "300 workloads from overseas providers into Indonesian-registered infrastructure "
                "at Cyber 1 and TIFA. Three patterns keep recurring across industries as diverse "
                "as fintech, healthcare, and e-commerce.</p>"
                "<h2>1. Data sovereignty is now a board-level topic</h2>"
                "<p>PDP Law (UU PDP 27/2022) has made cross-border data flow a compliance risk "
                "that many boards no longer accept. Hosting locally with a PSE-registered "
                "operator removes an entire class of legal ambiguity.</p>"
                "<h2>2. Latency to end-users is a revenue lever</h2>"
                "<p>An e-commerce client cut cart-abandonment 11% after moving from Singapore "
                "to Jakarta. Every 200ms saved on TTFB translated directly into conversion.</p>"
                "<h2>3. IDR-denominated billing removes FX surprise</h2>"
                "<p>Finance teams appreciate not having to hedge USD invoices month after month.</p>"
                "<p><em>Ready to explore whether local hosting fits your workload? "
                "<a href='/portal/register'>Create a portal account</a> and one of our solution "
                "architects will schedule a discovery call.</em></p>"
            ),
            "cover_image_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1600&q=70",
            "video_url": "",
            "author_name": "Intercloud Editorial",
            "tags": ["cloud", "indonesia", "compliance", "case-study"],
            "category": "Insight",
            "status": "published",
            "published_at": now,
            "meta_title": "Why Indonesian enterprises are moving workloads to local cloud",
            "meta_description": "Data sovereignty, latency, and cost are reshaping how Indonesian businesses choose infrastructure. Lessons from 300+ Intercloud migrations.",
            "meta_keywords": ["cloud indonesia", "data sovereignty", "pdp law", "local cloud", "cyber 1"],
            "og_image_url": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1200&q=80",
            "is_featured": True,
        },
        {
            "title": "Colocation vs. dedicated servers vs. VPS — a practical guide",
            "slug": "colocation-vs-dedicated-vs-vps",
            "excerpt": "Three infrastructure models that seem similar on paper but differ enormously in TCO, control, and operational overhead. This is our decision framework.",
            "body_html": (
                "<p>Choosing between colocation, dedicated servers, and VPS is one of the "
                "most frequent questions we hear from prospects. There's no universally "
                "correct answer &mdash; but there is a decision framework that reliably "
                "converges on the right choice.</p>"
                "<h2>The three axes that matter</h2>"
                "<ol>"
                "<li><b>Control:</b> Do you need root-of-trust hardware, or is a hypervisor slice enough?</li>"
                "<li><b>Scale profile:</b> Steady-state or spiky?</li>"
                "<li><b>Team capability:</b> Do you have SysAdmins on payroll, or do you want us to handle it?</li>"
                "</ol>"
                "<h2>Quick heuristic</h2>"
                "<ul>"
                "<li><b>VPS</b> when you want to move fast and treat servers like cattle.</li>"
                "<li><b>Dedicated</b> when you need consistent performance without noisy-neighbour risk.</li>"
                "<li><b>Colocation</b> when you own the hardware and need Tier-III power &amp; connectivity.</li>"
                "</ul>"
                "<p>Still not sure? Our sales engineers do free architecture reviews.</p>"
            ),
            "cover_image_url": "https://images.unsplash.com/photo-1591808216268-ce0b82787efe?auto=format&fit=crop&w=1600&q=70",
            "video_url": "",
            "author_name": "Intercloud Solutions",
            "tags": ["colocation", "dedicated-server", "vps", "guide"],
            "category": "Guide",
            "status": "published",
            "published_at": now,
            "meta_title": "Colocation vs Dedicated vs VPS — Practical Decision Guide",
            "meta_description": "A framework for choosing between colocation, dedicated servers, and VPS based on control, scale, and team capability.",
            "meta_keywords": ["colocation jakarta", "dedicated server", "vps indonesia", "infrastructure guide"],
            "og_image_url": "https://images.unsplash.com/photo-1591808216268-ce0b82787efe?auto=format&fit=crop&w=1200&q=80",
            "is_featured": False,
        },
        {
            "title": "Scheduled maintenance window — Cyber 1 core network upgrade",
            "slug": "cyber-1-core-network-upgrade-notice",
            "excerpt": "We're upgrading core routers at Cyber 1 to 400G capacity. Here's the schedule, impact, and what your team needs to know.",
            "body_html": (
                "<p>Between <b>02:00 and 04:00 WIB on Saturday, 22 March 2026</b>, our network "
                "engineering team will upgrade both Cyber 1 core routers to 400G-capable "
                "line cards.</p>"
                "<h2>Expected impact</h2>"
                "<p>Fail-over is designed to be non-disruptive; individual sessions may see "
                "brief 200&ndash;800ms delays as BGP re-converges. Services routed via alternate "
                "PoPs (TIFA, APJII) are unaffected.</p>"
                "<h2>Action required</h2>"
                "<p>None &mdash; but we recommend not running any critical batch job that requires "
                "sub-second network jitter guarantees during the window.</p>"
                "<p>Questions? Contact NOC at <a href='mailto:noc@intercloud-digital.com'>noc@intercloud-digital.com</a>.</p>"
            ),
            "cover_image_url": "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=1600&q=70",
            "video_url": "",
            "author_name": "Intercloud NOC",
            "tags": ["network", "maintenance", "announcement"],
            "category": "Announcement",
            "status": "published",
            "published_at": now,
            "meta_title": "Scheduled maintenance — Cyber 1 core network upgrade",
            "meta_description": "Intercloud will upgrade Cyber 1 core routers to 400G capacity on 22 March 2026, 02:00–04:00 WIB.",
            "meta_keywords": ["maintenance", "cyber 1", "network upgrade"],
            "og_image_url": "",
            "is_featured": False,
        },
    ]
    for a in demos:
        if await db.articles.find_one({"slug": a["slug"]}):
            continue
        a.setdefault("view_count", 0)
        a["created_at"] = now
        a["updated_at"] = now
        await db.articles.insert_one(a)
