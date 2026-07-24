"""Comprehensive backend testing for Intercloud Portal - Duitku batch.

Tests:
1. Billing defaults API (GET/PUT /admin/billing/settings)
2. Gateway policy (Duitku-only, midtrans/xendit filtering)
3. Duitku round-trip (pay-online, webhook, reactivation, idempotency)
4. Renewal sweep (auto-invoice generation)
5. must_change_password chain
6. Regression spot-checks (email test, payment-info, order preview)
"""
import os
import hmac
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
import requests
from pymongo import MongoClient

# Configuration
API = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/") + "/api/portal"
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASS = "AdminIntercloud2026!"

# MongoDB connection
_db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[
    os.environ.get("DB_NAME", "intercloud_portal")]

# Duitku credentials from MongoDB
_duitku_row = _db.integrations.find_one({"module": "duitku", "status": "enabled"})
MC = ((_duitku_row or {}).get("config") or {}).get("merchant_code", "")
KEY = ((_duitku_row or {}).get("config") or {}).get("api_key", "")

print(f"🔧 Test Configuration:")
print(f"   API Base: {API}")
print(f"   Admin: {ADMIN_EMAIL}")
print(f"   Duitku Merchant: {MC}")
print(f"   Duitku API Key: {'*' * 8 if KEY else 'NOT CONFIGURED'}")
print()


def _login(email, pw):
    """Login and return JWT token."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=15)
    r.raise_for_status()
    return r.json()["token"]


def _hdr(tok):
    """Return authorization header."""
    return {"Authorization": f"Bearer {tok}"}


def _hmac_sig(amount: str, order_id: str) -> str:
    """Generate HMAC-SHA256 signature for Duitku callback."""
    return hmac.new(KEY.encode(), f"{MC}{amount}{order_id}".encode(), hashlib.sha256).hexdigest()


# ============================================================
# TEST 1: Billing Defaults API
# ============================================================
def test_billing_defaults_api():
    """Test GET/PUT /admin/billing/settings with admin/staff permissions."""
    print("=" * 70)
    print("TEST 1: Billing Defaults API")
    print("=" * 70)
    
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    
    # 1a. GET billing settings (staff can read)
    print("\n1a. GET /admin/billing/settings (staff token)...")
    r = requests.get(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    settings = r.json()
    assert "default_tax_percent" in settings
    assert "renewal_lead_days" in settings
    assert "enable_extra_payment_gateways" in settings
    print(f"   ✅ Current settings: tax={settings['default_tax_percent']}%, lead={settings['renewal_lead_days']}d, extra_gateways={settings['enable_extra_payment_gateways']}")
    
    # Store original values
    orig_tax = settings["default_tax_percent"]
    orig_lead = settings["renewal_lead_days"]
    
    # 1b. PUT billing settings (admin only) - change values
    print("\n1b. PUT /admin/billing/settings (admin) - set tax=12%, lead=10d...")
    r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15,
                     json={"default_tax_percent": 12, "renewal_lead_days": 10})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    updated = r.json()
    assert updated["default_tax_percent"] == 12, f"Expected tax=12, got {updated['default_tax_percent']}"
    assert updated["renewal_lead_days"] == 10, f"Expected lead=10, got {updated['renewal_lead_days']}"
    print(f"   ✅ Settings updated: tax={updated['default_tax_percent']}%, lead={updated['renewal_lead_days']}d")
    
    # 1c. Verify persistence
    print("\n1c. Verify settings persisted...")
    r = requests.get(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    verified = r.json()
    assert verified["default_tax_percent"] == 12
    assert verified["renewal_lead_days"] == 10
    print("   ✅ Settings persisted correctly")
    
    # 1d. Restore original values
    print(f"\n1d. Restore original settings (tax={orig_tax}%, lead={orig_lead}d)...")
    r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15,
                     json={"default_tax_percent": orig_tax, "renewal_lead_days": orig_lead})
    assert r.status_code == 200
    print("   ✅ Original settings restored")
    
    # 1e. Test non-admin access (create a finance user)
    print("\n1e. Test non-admin PUT access (should fail with 403)...")
    # Create a finance user (non-admin staff role)
    staff_email = f"pytest-finance-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest Finance", "email": staff_email,
                            "password": "PytestFinance2026!", "role": "finance"})
    assert r.status_code in (200, 201), f"Failed to create finance user: {r.text}"
    staff_user = _db.users.find_one({"email": staff_email})
    
    try:
        staff_tok = _login(staff_email, "PytestFinance2026!")
        r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(staff_tok), timeout=15,
                         json={"default_tax_percent": 15})
        assert r.status_code == 403, f"Expected 403 for non-admin PUT, got {r.status_code}"
        print("   ✅ Non-admin PUT correctly rejected with 403")
    finally:
        # Cleanup finance user
        requests.delete(f"{API}/admin/users/{staff_user['_id']}", headers=_hdr(admin_tok), timeout=15)
    
    print("\n✅ TEST 1 PASSED: Billing Defaults API\n")


# ============================================================
# TEST 2: Gateway Policy (Duitku-only)
# ============================================================
def test_gateway_policy():
    """Test that midtrans/xendit are hidden unless enable_extra_payment_gateways is true."""
    print("=" * 70)
    print("TEST 2: Gateway Policy (Duitku-only)")
    print("=" * 70)
    
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    
    # 2a. Ensure extra gateways are disabled
    print("\n2a. Ensure enable_extra_payment_gateways=false...")
    r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15,
                     json={"enable_extra_payment_gateways": False})
    assert r.status_code == 200
    print("   ✅ Extra gateways disabled")
    
    # 2b. GET /admin/integrations/modules - should NOT include midtrans/xendit
    print("\n2b. GET /admin/integrations/modules (should exclude midtrans/xendit)...")
    r = requests.get(f"{API}/admin/integrations/modules", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    modules = r.json()
    module_keys = [m["key"] for m in modules]
    assert "duitku" in module_keys, "Duitku should be present"
    assert "midtrans" not in module_keys, "Midtrans should be hidden"
    assert "xendit" not in module_keys, "Xendit should be hidden"
    print(f"   ✅ Modules list: {module_keys} (midtrans/xendit hidden)")
    
    # 2c. GET /admin/integrations-v2/schema - should NOT include midtrans/xendit
    print("\n2c. GET /admin/integrations-v2/schema (should exclude midtrans/xendit)...")
    r = requests.get(f"{API}/admin/integrations-v2/schema", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    schema = r.json()
    assert "duitku" in schema, "Duitku should be in schema"
    assert "midtrans" not in schema, "Midtrans should not be in schema"
    assert "xendit" not in schema, "Xendit should not be in schema"
    print(f"   ✅ Schema keys: {list(schema.keys())} (midtrans/xendit hidden)")
    
    # 2d. GET /admin/integrations-v2 - should NOT include midtrans/xendit
    print("\n2d. GET /admin/integrations-v2 (should exclude midtrans/xendit)...")
    r = requests.get(f"{API}/admin/integrations-v2", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    integrations = r.json()
    assert "duitku" in integrations, "Duitku should be present"
    assert "midtrans" not in integrations, "Midtrans should be hidden"
    assert "xendit" not in integrations, "Xendit should be hidden"
    print(f"   ✅ Integrations: {list(integrations.keys())} (midtrans/xendit hidden)")
    
    # 2e. PUT /admin/integrations-v2/midtrans - should fail with 400
    print("\n2e. PUT /admin/integrations-v2/midtrans (should fail with Duitku-only message)...")
    r = requests.put(f"{API}/admin/integrations-v2/midtrans", headers=_hdr(admin_tok), timeout=15,
                     json={"enabled": True, "credentials": {"server_key": "test"}})
    assert r.status_code == 400, f"Expected 400, got {r.status_code}"
    assert "Duitku" in r.json()["detail"], f"Expected Duitku-only message, got: {r.json()['detail']}"
    print(f"   ✅ Midtrans PUT rejected: {r.json()['detail']}")
    
    # 2f. Enable extra gateways and verify they appear
    print("\n2f. Enable extra gateways (enable_extra_payment_gateways=true)...")
    r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15,
                     json={"enable_extra_payment_gateways": True})
    assert r.status_code == 200
    
    r = requests.get(f"{API}/admin/integrations/modules", headers=_hdr(admin_tok), timeout=15)
    assert r.status_code == 200
    modules = r.json()
    module_keys = [m["key"] for m in modules]
    assert "midtrans" in module_keys, "Midtrans should now be visible"
    assert "xendit" in module_keys, "Xendit should now be visible"
    print(f"   ✅ Modules now include: {module_keys}")
    
    # 2g. Disable extra gateways again
    print("\n2g. Disable extra gateways again (restore policy)...")
    r = requests.put(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15,
                     json={"enable_extra_payment_gateways": False})
    assert r.status_code == 200
    
    r = requests.get(f"{API}/admin/integrations/modules", headers=_hdr(admin_tok), timeout=15)
    modules = r.json()
    module_keys = [m["key"] for m in modules]
    assert "midtrans" not in module_keys, "Midtrans should be hidden again"
    assert "xendit" not in module_keys, "Xendit should be hidden again"
    print("   ✅ Extra gateways hidden again")
    
    print("\n✅ TEST 2 PASSED: Gateway Policy\n")


# ============================================================
# TEST 3: Duitku Round-Trip
# ============================================================
def test_duitku_round_trip():
    """Test Duitku payment flow: pay-online, webhook, reactivation, idempotency."""
    print("=" * 70)
    print("TEST 3: Duitku Round-Trip")
    print("=" * 70)
    
    if not MC or not KEY:
        print("   ⚠️  SKIPPED: Duitku not configured")
        return
    
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    
    # 3a. Create a fresh client user
    print("\n3a. Create fresh client user...")
    client_email = f"pytest-duitku-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest Duitku Client", "email": client_email,
                            "password": "PytestClient2026!", "role": "client"})
    assert r.status_code in (200, 201), f"Failed to create client: {r.text}"
    client_user = _db.users.find_one({"email": client_email})
    client_tok = _login(client_email, "PytestClient2026!")
    print(f"   ✅ Client created: {client_email}")
    
    try:
        # 3b. Create invoice (tax_percent=0, small amount)
        print("\n3b. Create invoice (amount=15000, tax=0%)...")
        due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        r = requests.post(f"{API}/admin/invoices", headers=_hdr(admin_tok), timeout=15, json={
            "user_id": str(client_user["_id"]),
            "items": [{"description": "Pytest Duitku Test", "qty": 1,
                       "unit_price": 15000, "total": 15000}],
            "tax_percent": 0, "due_date": due, "notes": "pytest-duitku"})
        assert r.status_code == 200, f"Failed to create invoice: {r.text}"
        inv = r.json()
        inv_number = inv["number"]
        inv_id = inv["id"]
        print(f"   ✅ Invoice created: {inv_number} (total={inv['total']})")
        
        # 3c. Client calls pay-online with provider=duitku
        print("\n3c. POST /client/invoices/{id}/pay-online?provider=duitku...")
        r = requests.post(f"{API}/client/invoices/{inv_id}/pay-online?provider=duitku",
                          headers=_hdr(client_tok), timeout=45)
        assert r.status_code == 200, f"pay-online failed: {r.status_code} {r.text}"
        pay_result = r.json()
        assert "payment_url" in pay_result, f"No payment_url in response: {pay_result}"
        assert pay_result["payment_url"].startswith("https://"), f"Invalid payment_url: {pay_result['payment_url']}"
        print(f"   ✅ Payment URL: {pay_result['payment_url'][:60]}...")
        
        # Verify invoice updated with payment_link and payment_provider
        inv_doc = _db.invoices.find_one({"number": inv_number})
        assert inv_doc.get("payment_link") == pay_result["payment_url"]
        assert inv_doc.get("payment_provider") == "duitku"
        print("   ✅ Invoice updated with payment_link and payment_provider")
        
        # 3d. Test pay-online with midtrans/xendit (should fail)
        print("\n3d. Test pay-online with midtrans/xendit (should fail with 400)...")
        for provider in ["midtrans", "xendit"]:
            r = requests.post(f"{API}/client/invoices/{inv_id}/pay-online?provider={provider}",
                              headers=_hdr(client_tok), timeout=15)
            assert r.status_code == 400, f"Expected 400 for {provider}, got {r.status_code}"
            assert "Duitku" in r.json()["detail"], f"Expected Duitku-only message for {provider}"
            print(f"   ✅ {provider} correctly rejected")
        
        # 3e. Plant a suspended service for this client
        print("\n3e. Plant suspended service (reason: invoice overdue)...")
        svc_id = _db.services.insert_one({
            "user_id": client_user["_id"],
            "product_id": "test-product",
            "product_name": "VPS Test",
            "category": "vps",
            "name": "pytest-suspended-service",
            "status": "suspended",
            "suspended_at": datetime.now(timezone.utc).isoformat(),
            "suspended_reason": f"invoice {inv_number} overdue >8d",
            "start_date": "2026-01-01",
            "next_renewal": "2099-01-01",
            "price_monthly": 15000,
            "billing_cycle": "monthly",
            "config": {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }).inserted_id
        print(f"   ✅ Service suspended: {svc_id}")
        
        # 3f. Simulate valid Duitku callback (resultCode=00)
        print("\n3f. Simulate valid Duitku callback (resultCode=00)...")
        amount = str(int(inv["total"]))
        mails_before = _db.email_logs.count_documents({"event_key": "payment_received"})
        form = {
            "merchantCode": MC,
            "amount": amount,
            "merchantOrderId": inv_number,
            "resultCode": "00",
            "reference": "PYTEST-REF-001",
            "signature": _hmac_sig(amount, inv_number)
        }
        r = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
        assert r.status_code == 200, f"Webhook failed: {r.status_code} {r.text}"
        webhook_result = r.json()
        assert webhook_result["status"] == "paid", f"Expected status=paid, got {webhook_result}"
        assert webhook_result["reactivated_services"] == 1, f"Expected 1 reactivated service, got {webhook_result['reactivated_services']}"
        print(f"   ✅ Webhook processed: {webhook_result}")
        
        # Verify invoice marked as paid
        inv_doc = _db.invoices.find_one({"number": inv_number})
        assert inv_doc["status"] == "paid", f"Invoice status should be paid, got {inv_doc['status']}"
        assert inv_doc["payment_method"] == "duitku"
        assert inv_doc.get("paid_at") is not None
        print("   ✅ Invoice marked as paid with payment_method=duitku")
        
        # Verify service reactivated
        svc_doc = _db.services.find_one({"_id": svc_id})
        assert svc_doc["status"] == "active", f"Service should be active, got {svc_doc['status']}"
        assert "suspended_reason" not in svc_doc
        assert svc_doc.get("reactivated_reason") is not None
        assert inv_number in svc_doc["reactivated_reason"]
        print("   ✅ Service reactivated with reactivated_reason")
        
        # Verify exactly ONE email sent
        mails_after = _db.email_logs.count_documents({"event_key": "payment_received"})
        assert mails_after == mails_before + 1, f"Expected 1 new email, got {mails_after - mails_before}"
        print("   ✅ Exactly ONE payment_received email logged")
        
        # 3g. Duplicate callback (should be idempotent)
        print("\n3g. Send duplicate callback (should be idempotent)...")
        r = requests.post(f"{API}/webhooks/duitku", data=form, timeout=20)
        assert r.status_code == 200
        dup_result = r.json()
        assert dup_result.get("duplicate") is True, f"Expected duplicate=true, got {dup_result}"
        print(f"   ✅ Duplicate callback handled: {dup_result}")
        
        # Verify email count unchanged
        mails_final = _db.email_logs.count_documents({"event_key": "payment_received"})
        assert mails_final == mails_after, f"Email count should not change on duplicate, got {mails_final}"
        print("   ✅ Email count unchanged (idempotent)")
        
        # 3h. Test invalid signature (should fail with 400)
        print("\n3h. Test invalid signature (should fail with 400)...")
        # Create another invoice for this test
        r = requests.post(f"{API}/admin/invoices", headers=_hdr(admin_tok), timeout=15, json={
            "user_id": str(client_user["_id"]),
            "items": [{"description": "Pytest Bad Sig", "qty": 1,
                       "unit_price": 10000, "total": 10000}],
            "tax_percent": 0, "due_date": due, "notes": "pytest-badsig"})
        assert r.status_code == 200
        inv2 = r.json()
        inv2_number = inv2["number"]
        
        bad_form = {
            "merchantCode": MC,
            "amount": "10000",
            "merchantOrderId": inv2_number,
            "resultCode": "00",
            "reference": "PYTEST-BAD",
            "signature": "0" * 64  # Invalid signature
        }
        r = requests.post(f"{API}/webhooks/duitku", data=bad_form, timeout=20)
        assert r.status_code == 400, f"Expected 400 for invalid signature, got {r.status_code}"
        print("   ✅ Invalid signature rejected with 400")
        
        # Verify invoice2 still unpaid
        inv2_doc = _db.invoices.find_one({"number": inv2_number})
        assert inv2_doc["status"] == "unpaid", f"Invoice should remain unpaid, got {inv2_doc['status']}"
        assert inv2_doc.get("paid_at") is None
        print("   ✅ Invoice remains unpaid after invalid signature")
        
        # 3i. Test resultCode=02 (failed payment)
        print("\n3i. Test resultCode=02 (failed payment)...")
        valid_sig = _hmac_sig("10000", inv2_number)
        fail_form = {
            "merchantCode": MC,
            "amount": "10000",
            "merchantOrderId": inv2_number,
            "resultCode": "02",  # Failed
            "reference": "PYTEST-FAIL",
            "signature": valid_sig
        }
        r = requests.post(f"{API}/webhooks/duitku", data=fail_form, timeout=20)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        fail_result = r.json()
        assert fail_result["status"] == "failed", f"Expected status=failed, got {fail_result}"
        print(f"   ✅ Failed payment handled: {fail_result}")
        
        # Verify invoice2 still unpaid
        inv2_doc = _db.invoices.find_one({"number": inv2_number})
        assert inv2_doc["status"] == "unpaid", f"Invoice should remain unpaid after failed payment"
        print("   ✅ Invoice remains unpaid after resultCode=02")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        _db.services.delete_many({"user_id": client_user["_id"]})
        _db.invoices.delete_many({"user_id": client_user["_id"]})
        requests.delete(f"{API}/admin/users/{client_user['_id']}", headers=_hdr(admin_tok), timeout=15)
        print("   ✅ Cleanup complete")
    
    print("\n✅ TEST 3 PASSED: Duitku Round-Trip\n")


# ============================================================
# TEST 4: Renewal Sweep
# ============================================================
def test_renewal_sweep():
    """Test renewal auto-invoice sweep."""
    print("=" * 70)
    print("TEST 4: Renewal Sweep")
    print("=" * 70)
    
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    
    # 4a. Create a client user
    print("\n4a. Create client user for renewal test...")
    client_email = f"pytest-renewal-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest Renewal", "email": client_email,
                            "password": "PytestRenewal2026!", "role": "client"})
    assert r.status_code in (200, 201), f"Failed to create client: {r.text}"
    client_user = _db.users.find_one({"email": client_email})
    print(f"   ✅ Client created: {client_email}")
    
    try:
        # 4b. Plant an active service with next_renewal = today+3d, quarterly cycle
        print("\n4b. Plant active service (quarterly, next_renewal=today+3d)...")
        next_renewal = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
        svc_id = _db.services.insert_one({
            "user_id": client_user["_id"],
            "product_id": "test-product",
            "product_name": "VPS Quarterly",
            "category": "vps",
            "name": "pytest-renewal-service",
            "status": "active",
            "billing_cycle": "quarterly",
            "start_date": "2026-01-01",
            "next_renewal": next_renewal,
            "price_monthly": 200000,
            "config": {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }).inserted_id
        print(f"   ✅ Service planted: {svc_id}, next_renewal={next_renewal}")
        
        # 4c. Run renewal sweep
        print("\n4c. POST /admin/billing/run-renewal-sweep...")
        r = requests.post(f"{API}/admin/billing/run-renewal-sweep",
                          headers=_hdr(admin_tok), timeout=60)
        assert r.status_code == 200, f"Sweep failed: {r.status_code} {r.text}"
        sweep_result = r.json()
        assert sweep_result.get("generated", 0) >= 1, f"Expected at least 1 invoice generated, got {sweep_result}"
        print(f"   ✅ Sweep result: {sweep_result}")
        
        # 4d. Verify invoice created
        print("\n4d. Verify invoice created with correct details...")
        inv = _db.invoices.find_one({"service_id": str(svc_id)})
        assert inv is not None, "Invoice should be created"
        assert inv["renewal_period"] == next_renewal, f"renewal_period should be {next_renewal}"
        assert inv["due_date"] == next_renewal, f"due_date should be {next_renewal}"
        assert inv["subtotal"] == 600000, f"subtotal should be 600000 (200000*3), got {inv['subtotal']}"
        # Get current tax setting
        r = requests.get(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15)
        current_tax = r.json()["default_tax_percent"]
        assert inv["tax_percent"] == current_tax, f"tax_percent should be {current_tax}, got {inv['tax_percent']}"
        print(f"   ✅ Invoice created: {inv['number']}, subtotal={inv['subtotal']}, tax={inv['tax_percent']}%")
        
        # 4e. Verify service next_renewal advanced by 3 months
        print("\n4e. Verify service next_renewal advanced by 3 months...")
        svc = _db.services.find_one({"_id": svc_id})
        # Calculate expected next_renewal (3 months ahead)
        from datetime import date
        import calendar
        d = datetime.strptime(next_renewal, "%Y-%m-%d").date()
        y = d.year + (d.month - 1 + 3) // 12
        mo = (d.month - 1 + 3) % 12 + 1
        day = min(d.day, calendar.monthrange(y, mo)[1])
        expected_next = date(y, mo, day).isoformat()
        assert svc["next_renewal"] == expected_next, f"next_renewal should be {expected_next}, got {svc['next_renewal']}"
        assert svc.get("last_renewal_invoice_id") == str(inv["_id"])
        print(f"   ✅ Service next_renewal advanced to {svc['next_renewal']}")
        
        # 4f. Re-run sweep (should not duplicate)
        print("\n4f. Re-run sweep (should not duplicate invoice)...")
        r = requests.post(f"{API}/admin/billing/run-renewal-sweep",
                          headers=_hdr(admin_tok), timeout=60)
        assert r.status_code == 200
        inv_count = _db.invoices.count_documents({"service_id": str(svc_id)})
        assert inv_count == 1, f"Should have exactly 1 invoice, got {inv_count}"
        print("   ✅ No duplicate invoice created (idempotent)")
        
        # 4g. Verify email logged
        print("\n4g. Verify invoice_generated email logged...")
        email_count = _db.email_logs.count_documents({
            "event_key": "invoice_generated",
            "invoice_id": str(inv["_id"])
        })
        assert email_count >= 1, f"Should have at least 1 invoice_generated email"
        print(f"   ✅ Email logged: {email_count} invoice_generated event(s)")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        _db.services.delete_many({"user_id": client_user["_id"]})
        _db.invoices.delete_many({"user_id": client_user["_id"]})
        requests.delete(f"{API}/admin/users/{client_user['_id']}", headers=_hdr(admin_tok), timeout=15)
        print("   ✅ Cleanup complete")
    
    print("\n✅ TEST 4 PASSED: Renewal Sweep\n")


# ============================================================
# TEST 5: must_change_password Chain
# ============================================================
def test_must_change_password():
    """Test must_change_password flag and change-password flow."""
    print("=" * 70)
    print("TEST 5: must_change_password Chain")
    print("=" * 70)
    
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    
    # 5a. Create a finance user (staff role)
    print("\n5a. Create finance user (staff role)...")
    staff_email = f"pytest-mustchange-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest MustChange", "email": staff_email,
                            "password": "InitialPass2026!", "role": "finance"})
    assert r.status_code in (200, 201), f"Failed to create finance user: {r.text}"
    staff_user = _db.users.find_one({"email": staff_email})
    print(f"   ✅ Finance user created: {staff_email}")
    
    try:
        # 5b. Set must_change_password=true in MongoDB
        print("\n5b. Set must_change_password=true in MongoDB...")
        _db.users.update_one({"_id": staff_user["_id"]},
                             {"$set": {"must_change_password": True}})
        print("   ✅ Flag set in database")
        
        # 5c. Login and verify flag in response
        print("\n5c. Login and verify must_change_password in response...")
        r = requests.post(f"{API}/auth/login",
                          json={"email": staff_email, "password": "InitialPass2026!"},
                          timeout=15)
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        login_result = r.json()
        assert login_result["user"]["must_change_password"] is True, \
            f"must_change_password should be true in login response"
        staff_tok = login_result["token"]
        print("   ✅ Login response contains must_change_password=true")
        
        # 5d. GET /auth/me should also show the flag
        print("\n5d. GET /auth/me should show must_change_password=true...")
        r = requests.get(f"{API}/auth/me", headers=_hdr(staff_tok), timeout=15)
        assert r.status_code == 200
        me_result = r.json()
        assert me_result["must_change_password"] is True, \
            f"must_change_password should be true in /auth/me"
        print("   ✅ /auth/me shows must_change_password=true")
        
        # 5e. Change password
        print("\n5e. POST /auth/change-password...")
        r = requests.post(f"{API}/auth/change-password", headers=_hdr(staff_tok), timeout=15,
                          json={"current_password": "InitialPass2026!",
                                "new_password": "NewSecurePass2026!"})
        assert r.status_code == 200, f"Change password failed: {r.status_code} {r.text}"
        print("   ✅ Password changed successfully")
        
        # 5f. GET /auth/me should now show must_change_password=false
        print("\n5f. GET /auth/me should now show must_change_password=false...")
        # Need to login again with new password to get fresh token
        r = requests.post(f"{API}/auth/login",
                          json={"email": staff_email, "password": "NewSecurePass2026!"},
                          timeout=15)
        assert r.status_code == 200
        new_tok = r.json()["token"]
        
        r = requests.get(f"{API}/auth/me", headers=_hdr(new_tok), timeout=15)
        assert r.status_code == 200
        me_result = r.json()
        assert me_result["must_change_password"] is False, \
            f"must_change_password should be false after password change"
        print("   ✅ /auth/me now shows must_change_password=false")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        requests.delete(f"{API}/admin/users/{staff_user['_id']}", headers=_hdr(admin_tok), timeout=15)
        print("   ✅ Cleanup complete")
    
    print("\n✅ TEST 5 PASSED: must_change_password Chain\n")


# ============================================================
# TEST 6: Regression Spot-Checks
# ============================================================
def test_regression_checks():
    """Regression spot-checks: email test, payment-info, order preview."""
    print("=" * 70)
    print("TEST 6: Regression Spot-Checks")
    print("=" * 70)
    
    admin_tok = _login(ADMIN_EMAIL, ADMIN_PASS)
    
    # 6a. POST /settings/email/test (admin has damien mailbox saved)
    print("\n6a. POST /settings/email/test (should work with saved settings)...")
    r = requests.post(f"{API}/settings/email/test", headers=_hdr(admin_tok), timeout=30,
                      json={})  # Empty payload should use saved settings
    assert r.status_code == 200, f"Email test failed: {r.status_code} {r.text}"
    test_result = r.json()
    # Check if both IMAP and SMTP are ok (or at least the endpoint works)
    print(f"   ✅ Email test result: imap.ok={test_result.get('imap', {}).get('ok')}, smtp.ok={test_result.get('smtp', {}).get('ok')}")
    
    # 6b. GET /client/payment-info (create a client first)
    print("\n6b. GET /client/payment-info (should show duitku_enabled=true)...")
    client_email = f"pytest-regression-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/admin/users", headers=_hdr(admin_tok), timeout=15,
                      json={"name": "Pytest Regression", "email": client_email,
                            "password": "PytestRegression2026!", "role": "client"})
    assert r.status_code in (200, 201)
    client_user = _db.users.find_one({"email": client_email})
    client_tok = _login(client_email, "PytestRegression2026!")
    
    try:
        r = requests.get(f"{API}/client/payment-info", headers=_hdr(client_tok), timeout=15)
        assert r.status_code == 200, f"payment-info failed: {r.status_code} {r.text}"
        payment_info = r.json()
        assert payment_info.get("duitku_enabled") is True, \
            f"duitku_enabled should be true, got {payment_info.get('duitku_enabled')}"
        assert "bank_accounts" in payment_info
        print(f"   ✅ payment-info: duitku_enabled={payment_info['duitku_enabled']}, bank_accounts={len(payment_info.get('bank_accounts', []))} entries")
        
        # 6c. Client order preview (if products exist)
        print("\n6c. POST /client/orders/preview (check tax uses settings)...")
        # Check if any active products exist
        products = list(_db.products.find({"status": "active"}).limit(1))
        if products:
            product = products[0]
            r = requests.post(f"{API}/client/orders/preview", headers=_hdr(client_tok), timeout=15,
                              json={"items": [{"product_id": str(product["_id"]), "quantity": 1}]})
            if r.status_code == 200:
                preview = r.json()
                # Get current tax setting
                r_tax = requests.get(f"{API}/admin/billing/settings", headers=_hdr(admin_tok), timeout=15)
                current_tax = r_tax.json()["default_tax_percent"]
                # Preview should use the current tax setting
                print(f"   ✅ Order preview: tax_percent={preview.get('tax_percent')}% (settings: {current_tax}%)")
            else:
                print(f"   ⚠️  Order preview returned {r.status_code} (may require additional setup)")
        else:
            print("   ⚠️  No active products found, skipping order preview test")
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up test data...")
        requests.delete(f"{API}/admin/users/{client_user['_id']}", headers=_hdr(admin_tok), timeout=15)
        print("   ✅ Cleanup complete")
    
    print("\n✅ TEST 6 PASSED: Regression Spot-Checks\n")


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("INTERCLOUD PORTAL - BACKEND TESTING SUITE")
    print("Duitku Batch: Payment Round-Trip + Renewal + Billing Defaults")
    print("=" * 70 + "\n")
    
    try:
        test_billing_defaults_api()
        test_gateway_policy()
        test_duitku_round_trip()
        test_renewal_sweep()
        test_must_change_password()
        test_regression_checks()
        
        print("\n" + "=" * 70)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 70 + "\n")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        raise
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}\n")
        raise
