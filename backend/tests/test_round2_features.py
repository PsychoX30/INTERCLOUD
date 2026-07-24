"""Round 2 regression tests — Sections A/B/C/D.

Covers:
  * A: NOC probe retention/rollup job (noc_daily_uptime) + run-retention endpoint
  * B: enforced CSP header, rate-limit config on public endpoints,
       audit-log immutability (no DELETE/PUT surface)
  * C: SEO dynamic-render endpoint for bots, sitemap includes /status
  * D: creative role (content write OK, billing/CRM 403),
       media library CRUD + 409-on-delete-while-used,
       content calendar CRUD + article-publish auto-sync,
       ticket <-> device linking
"""
from __future__ import annotations
import io
import os
import uuid

import requests
from pymongo import MongoClient

API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api/portal"
LOCAL_API = "http://127.0.0.1:8001/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS = "AdminIntercloud2026!"

_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


_TOKEN_CACHE: dict = {}


def _login(email, pw):
    """Cached login with 429 backoff — keeps the shared 10/min limiter happy."""
    import time as _t
    if email in _TOKEN_CACHE:
        return _TOKEN_CACHE[email]
    for _ in range(3):
        r = requests.post(f"{LOCAL_API}/auth/login", json={"email": email, "password": pw}, timeout=15)
        if r.status_code == 429:
            _t.sleep(int(r.headers.get("Retry-After", "60")) + 2)
            continue
        r.raise_for_status()
        _TOKEN_CACHE[email] = r.json()["token"]
        return _TOKEN_CACHE[email]
    r.raise_for_status()


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _db():
    cli = MongoClient(os.environ["MONGO_URL"])
    return cli[os.environ.get("DB_NAME", "intercloud")]


# ------------------------------------------------------------------
# Section B — security
# ------------------------------------------------------------------
class TestSecurityHeaders:
    def test_csp_enforced_header_present(self):
        r = requests.get(f"{LOCAL_API}/public/status", timeout=15)
        csp = r.headers.get("Content-Security-Policy", "")
        assert csp, "enforced Content-Security-Policy header must be present"
        assert "default-src" in csp
        assert "script-src" in csp
        assert "frame-ancestors 'none'" in csp

    def test_report_only_kept_as_safety_net(self):
        r = requests.get(f"{LOCAL_API}/public/status", timeout=15)
        assert r.headers.get("Content-Security-Policy-Report-Only"), \
            "report-only header kept for one release cycle"

    def test_audit_logs_are_append_only(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        # No DELETE/PUT surface may exist for audit logs.
        r = requests.delete(f"{LOCAL_API}/admin/audit-logs", headers=_hdr(tok), timeout=15)
        assert r.status_code in (404, 405), f"DELETE audit-logs must not exist, got {r.status_code}"
        r = requests.put(f"{LOCAL_API}/admin/audit-logs", headers=_hdr(tok), json={}, timeout=15)
        assert r.status_code in (404, 405), f"PUT audit-logs must not exist, got {r.status_code}"
        r = requests.delete(f"{LOCAL_API}/admin/audit-logs/000000000000000000000000",
                            headers=_hdr(tok), timeout=15)
        assert r.status_code in (404, 405)


# ------------------------------------------------------------------
# Section A — NOC retention / rollup
# ------------------------------------------------------------------
class TestNocRetention:
    def test_rollup_and_retention(self):
        db = _db()
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        dev_id = f"testdev-{uuid.uuid4().hex[:8]}"
        # Seed raw probes: 40 days ago (should be deleted), yesterday (rolled up)
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=40))
        yday = (now - timedelta(days=1))
        docs = []
        for i in range(4):
            docs.append({"device_id": dev_id, "ok": True,
                         "at": old.replace(hour=i).isoformat(), "created_at": old})
        for i in range(4):
            docs.append({"device_id": dev_id, "ok": i < 3,   # 75% uptime yesterday
                         "at": yday.replace(hour=i).isoformat(), "created_at": yday})
        db.noc_probes.insert_many(docs)
        try:
            r = requests.post(f"{LOCAL_API}/admin/noc/run-retention", headers=_hdr(tok), timeout=30)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["retention_days"] >= 1
            assert body["deleted_probes"] >= 4, "40-day-old probes must be deleted"
            # rollup rows exist for yesterday with correct pct
            row = db.noc_daily_uptime.find_one({"device_id": dev_id,
                                                "date": yday.strftime("%Y-%m-%d")})
            assert row, "daily rollup row must exist"
            assert row["sample_count"] == 4
            assert abs(row["uptime_pct"] - 75.0) < 0.01
            # raw old probes gone, yesterday's (within retention) still present
            assert db.noc_probes.count_documents({"device_id": dev_id,
                                                  "at": {"$lt": (now - timedelta(days=35)).isoformat()}}) == 0
        finally:
            db.noc_probes.delete_many({"device_id": dev_id})
            db.noc_daily_uptime.delete_many({"device_id": dev_id})

    def test_noc_events_never_deleted_by_retention(self):
        db = _db()
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        from datetime import datetime, timezone, timedelta
        old = datetime.now(timezone.utc) - timedelta(days=400)
        marker = f"retention-guard-{uuid.uuid4().hex[:8]}"
        db.noc_events.insert_one({"device_id": marker, "type": "device_down",
                                  "message": marker, "at": old.isoformat(),
                                  "created_at": old})
        try:
            requests.post(f"{LOCAL_API}/admin/noc/run-retention", headers=_hdr(tok), timeout=30)
            assert db.noc_events.count_documents({"device_id": marker}) == 1, \
                "noc_events are permanent history — retention must not touch them"
        finally:
            db.noc_events.delete_many({"device_id": marker})


# ------------------------------------------------------------------
# Section C — SEO
# ------------------------------------------------------------------
class TestSeoRendering:
    def _make_article(self, tok):
        slug = f"seo-test-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{LOCAL_API}/admin/articles", headers=_hdr(tok), json={
            "title": f"SEO Test {slug}", "slug": slug,
            "excerpt": "Excerpt for bot rendering.", "body_html": "<p>Body</p>",
            "status": "published", "meta_title": f"Meta {slug}",
            "meta_description": "Meta description for crawler.",
        }, timeout=15)
        r.raise_for_status()
        return r.json()

    def test_bot_render_returns_article_meta(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        a = self._make_article(tok)
        try:
            r = requests.get(f"{LOCAL_API}/seo/render/articles/{a['slug']}",
                             headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
                             timeout=15)
            assert r.status_code == 200
            html = r.text
            assert f"Meta {a['slug']}" in html, "article-specific meta_title must be in <title>"
            assert "<title>" in html and "og:title" in html and "application/ld+json" in html
            assert "Meta description for crawler." in html
            assert f"/articles/{a['slug']}" in html  # canonical
        finally:
            requests.delete(f"{LOCAL_API}/admin/articles/{a['id']}", headers=_hdr(tok), timeout=15)

    def test_bot_render_404_for_unknown_slug(self):
        r = requests.get(f"{LOCAL_API}/seo/render/articles/does-not-exist-xyz", timeout=15)
        assert r.status_code == 404

    def test_sitemap_includes_status_and_lastmod(self):
        r = requests.get(f"{LOCAL_API}/sitemap.xml", timeout=15)
        assert r.status_code == 200
        assert "/status" in r.text
        assert "<lastmod>" in r.text


# ------------------------------------------------------------------
# Section D — creative role
# ------------------------------------------------------------------
class TestCreativeRole:
    EMAIL = "creative-test@intercloud-digital.com"
    PASS = "Creative2026!"

    def _token(self):
        admin = _login(ADMIN_EMAIL, ADMIN_PASS)
        users = requests.get(f"{LOCAL_API}/admin/users", headers=_hdr(admin), timeout=15).json()
        hit = next((u for u in users if u["email"] == self.EMAIL), None)
        if hit:
            requests.put(f"{LOCAL_API}/admin/users/{hit['id']}", headers=_hdr(admin),
                         json={"password": self.PASS, "role": "creative"}, timeout=15)
        else:
            requests.post(f"{LOCAL_API}/admin/users", headers=_hdr(admin), json={
                "email": self.EMAIL, "password": self.PASS,
                "name": "Creative Tester", "role": "creative"}, timeout=15)
        return _login(self.EMAIL, self.PASS)

    def test_creative_can_write_articles(self):
        tok = self._token()
        slug = f"creative-{uuid.uuid4().hex[:8]}"
        r = requests.post(f"{LOCAL_API}/admin/articles", headers=_hdr(tok), json={
            "title": "By Creative", "slug": slug, "excerpt": "x",
            "body_html": "<p>x</p>", "status": "draft"}, timeout=15)
        assert r.status_code == 200, r.text
        aid = r.json()["id"]
        r = requests.delete(f"{LOCAL_API}/admin/articles/{aid}", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200

    def test_creative_blocked_from_finance_and_crm(self):
        tok = self._token()
        for path in ("/admin/invoices", "/admin/orders", "/admin/quotations",
                     "/admin/crm", "/admin/followups"):
            r = requests.get(f"{LOCAL_API}{path}", headers=_hdr(tok), timeout=15)
            assert r.status_code == 403, f"{path} must be 403 for creative, got {r.status_code}"
        # admin-only surfaces stay blocked too
        for path in ("/admin/noc/devices", "/admin/credit-notes", "/admin/audit-logs"):
            r = requests.get(f"{LOCAL_API}{path}", headers=_hdr(tok), timeout=15)
            assert r.status_code == 403, f"{path} must be 403 for creative, got {r.status_code}"

    def test_creative_can_use_media_and_calendar(self):
        tok = self._token()
        r = requests.get(f"{LOCAL_API}/admin/media", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200
        r = requests.get(f"{LOCAL_API}/admin/content-calendar", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200


# ------------------------------------------------------------------
# Section D — media library
# ------------------------------------------------------------------
class TestMediaLibrary:
    def test_upload_list_delete_flow(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        files = {"file": ("pixel.png", io.BytesIO(_PNG), "image/png")}
        r = requests.post(f"{LOCAL_API}/admin/media", headers=_hdr(tok), files=files,
                          data={"alt_text": "tiny pixel", "tags": "test, Pixel"}, timeout=15)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["tags"] == ["pixel", "test"]   # normalised lowercase + sorted
        # public file serve works
        f = requests.get(f"http://127.0.0.1:8001{m['url']}", timeout=15)
        assert f.status_code == 200 and f.headers["content-type"] == "image/png"
        # listed with tag filter
        rows = requests.get(f"{LOCAL_API}/admin/media?tag=pixel", headers=_hdr(tok), timeout=15).json()
        assert any(x["id"] == m["id"] for x in rows)
        # unused -> delete OK
        r = requests.delete(f"{LOCAL_API}/admin/media/{m['id']}", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200

    def test_delete_blocked_while_used(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        files = {"file": ("used.png", io.BytesIO(_PNG), "image/png")}
        m = requests.post(f"{LOCAL_API}/admin/media", headers=_hdr(tok), files=files,
                          data={"alt_text": "", "tags": ""}, timeout=15).json()
        slug = f"media-use-{uuid.uuid4().hex[:8]}"
        a = requests.post(f"{LOCAL_API}/admin/articles", headers=_hdr(tok), json={
            "title": "Uses media", "slug": slug, "excerpt": "x", "body_html": "<p>x</p>",
            "status": "draft", "cover_image_url": m["url"]}, timeout=15).json()
        try:
            r = requests.delete(f"{LOCAL_API}/admin/media/{m['id']}", headers=_hdr(tok), timeout=15)
            assert r.status_code == 409, f"in-use asset must be blocked, got {r.status_code}"
            detail = r.json()["detail"]
            assert detail["used_in"] and detail["used_in"][0]["type"] == "article"
        finally:
            requests.delete(f"{LOCAL_API}/admin/articles/{a['id']}", headers=_hdr(tok), timeout=15)
            requests.delete(f"{LOCAL_API}/admin/media/{m['id']}", headers=_hdr(tok), timeout=15)

    def test_upload_rejects_non_image(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        files = {"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")}
        r = requests.post(f"{LOCAL_API}/admin/media", headers=_hdr(tok), files=files,
                          data={"alt_text": "", "tags": ""}, timeout=15)
        assert r.status_code == 400


# ------------------------------------------------------------------
# Section D — content calendar
# ------------------------------------------------------------------
class TestContentCalendar:
    def test_crud(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        r = requests.post(f"{LOCAL_API}/admin/content-calendar", headers=_hdr(tok), json={
            "title": "IG teaser", "type": "social_post",
            "scheduled_at": "2026-07-01T09:00:00", "status": "scheduled"}, timeout=15)
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        r = requests.put(f"{LOCAL_API}/admin/content-calendar/{cid}", headers=_hdr(tok),
                         json={"status": "published"}, timeout=15)
        assert r.status_code == 200 and r.json()["status"] == "published"
        rows = requests.get(f"{LOCAL_API}/admin/content-calendar?date_from=2026-07-01&date_to=2026-07-31",
                            headers=_hdr(tok), timeout=15).json()
        assert any(x["id"] == cid for x in rows)
        r = requests.delete(f"{LOCAL_API}/admin/content-calendar/{cid}", headers=_hdr(tok), timeout=15)
        assert r.status_code == 200

    def test_invalid_type_rejected(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        r = requests.post(f"{LOCAL_API}/admin/content-calendar", headers=_hdr(tok),
                          json={"title": "x", "type": "billboard"}, timeout=15)
        assert r.status_code == 400

    def test_article_publish_syncs_calendar(self):
        tok = _login(ADMIN_EMAIL, ADMIN_PASS)
        slug = f"cal-sync-{uuid.uuid4().hex[:8]}"
        a = requests.post(f"{LOCAL_API}/admin/articles", headers=_hdr(tok), json={
            "title": "Sync me", "slug": slug, "excerpt": "x", "body_html": "<p>x</p>",
            "status": "published"}, timeout=15).json()
        try:
            rows = requests.get(f"{LOCAL_API}/admin/content-calendar", headers=_hdr(tok), timeout=15).json()
            hit = next((x for x in rows if x.get("linked_article_id") == a["id"]), None)
            assert hit, "publishing an article must upsert a calendar entry"
            assert hit["status"] == "published" and hit["type"] == "article"
        finally:
            requests.delete(f"{LOCAL_API}/admin/articles/{a['id']}", headers=_hdr(tok), timeout=15)
            db = _db()
            db.content_calendar.delete_many({"linked_article_id": a["id"]})


# ------------------------------------------------------------------
# Section D — ticket <-> device linking
# ------------------------------------------------------------------
class TestTicketDeviceLink:
    def test_ticket_created_with_device_and_filterable(self):
        admin = _login(ADMIN_EMAIL, ADMIN_PASS)
        client = _login("demo@client.com", "ClientDemo2026!")
        opts = requests.get(f"{LOCAL_API}/tickets/device-options", headers=_hdr(client), timeout=15)
        assert opts.status_code == 200
        options = opts.json()
        for o in options:
            assert set(o.keys()) == {"id", "name"}, "device options must not leak hosts/IPs"
        dev_id = options[0]["id"] if options else None
        payload = {"subject": f"Device link {uuid.uuid4().hex[:6]}", "department": "technical",
                   "priority": "high", "message": "link test"}
        if dev_id:
            payload["related_device_id"] = dev_id
        r = requests.post(f"{LOCAL_API}/client/tickets", headers=_hdr(client), json=payload, timeout=15)
        assert r.status_code == 200, r.text
        t = r.json()
        if dev_id:
            assert t["related_device_id"] == dev_id
            assert t.get("related_device_name")
            rows = requests.get(f"{LOCAL_API}/admin/tickets?device_id={dev_id}",
                                headers=_hdr(admin), timeout=15).json()
            assert any(x["id"] == t["id"] for x in rows)
        # cleanup
        db = _db()
        from bson import ObjectId
        db.tickets.delete_one({"_id": ObjectId(t["id"])})
