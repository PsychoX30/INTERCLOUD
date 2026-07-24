#!/usr/bin/env python3
"""
Backend test for Intercloud Portal webmail changes.
Tests POST /api/portal/settings/email/test and related endpoints.
"""
import os
import sys
import time
import requests
from datetime import datetime

# Read base URL from frontend/.env
BASE_URL = None
with open("/app/frontend/.env", "r") as f:
    for line in f:
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip()
            break

if not BASE_URL:
    print("❌ REACT_APP_BACKEND_URL not found in /app/frontend/.env")
    sys.exit(1)

API_BASE = f"{BASE_URL}/api/portal"
print(f"🔗 Testing against: {API_BASE}")

# Test credentials
ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"

# Real mailbox credentials (provided by user for testing)
REAL_MAILBOX = {
    "from_name": "Damien",
    "from_email": "damien@intercloud-digital.com",
    "imap": {
        "host": "mail.intercloud-digital.com",
        "port": 993,
        "username": "damien@intercloud-digital.com",
        "password": "@Mail!234",
        "use_ssl": True
    },
    "smtp": {
        "host": "mail.intercloud-digital.com",
        "port": 465,
        "username": "damien@intercloud-digital.com",
        "password": "@Mail!234",
        "use_ssl": True
    }
}

# Test results tracking
test_results = []
failed_tests = []

def log_test(name, passed, details=""):
    """Log test result"""
    status = "✅" if passed else "❌"
    print(f"{status} {name}")
    if details:
        print(f"   {details}")
    test_results.append({"name": name, "passed": passed, "details": details})
    if not passed:
        failed_tests.append({"name": name, "details": details})

def login_admin():
    """Login as admin and return token"""
    print("\n🔐 Logging in as admin...")
    resp = requests.post(f"{API_BASE}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if resp.status_code != 200:
        log_test("Admin login", False, f"Status {resp.status_code}: {resp.text}")
        return None
    
    data = resp.json()
    token = data.get("token")
    if not token:
        log_test("Admin login", False, "No token in response")
        return None
    
    log_test("Admin login", True, f"Token: {token[:20]}...")
    return token

def test_unauthenticated_access():
    """Test that endpoints require authentication"""
    print("\n📋 Test 1e: Unauthenticated access to /settings/email/test")
    
    resp = requests.post(f"{API_BASE}/settings/email/test", json=REAL_MAILBOX)
    if resp.status_code in [401, 403]:
        log_test("Unauthenticated /settings/email/test returns 401/403", True, f"Status: {resp.status_code}")
    else:
        log_test("Unauthenticated /settings/email/test returns 401/403", False, 
                f"Expected 401/403, got {resp.status_code}")

def test_save_email_settings(token):
    """Test 1a: Save email settings"""
    print("\n📋 Test 1a: Save email settings")
    
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(f"{API_BASE}/settings/email", json=REAL_MAILBOX, headers=headers)
    
    if resp.status_code != 200:
        log_test("Save email settings", False, f"Status {resp.status_code}: {resp.text}")
        return False
    
    data = resp.json()
    
    # Verify password is masked in response
    smtp_password = data.get("smtp", {}).get("credentials", {}).get("password", "")
    imap_password = data.get("imap", {}).get("credentials", {}).get("password", "")
    
    if set(smtp_password) == {"•"} and set(imap_password) == {"•"}:
        log_test("Save email settings - passwords masked in response", True, 
                f"SMTP pwd: {smtp_password}, IMAP pwd: {imap_password}")
    else:
        log_test("Save email settings - passwords masked in response", False,
                f"Passwords not properly masked. SMTP: {smtp_password}, IMAP: {imap_password}")
        return False
    
    # Verify configured flag
    if data.get("configured") == True:
        log_test("Save email settings - configured flag set", True)
    else:
        log_test("Save email settings - configured flag set", False, f"configured={data.get('configured')}")
        return False
    
    return True

def test_connection_with_masked_passwords(token):
    """Test 1b: Test connection with masked passwords (should fall back to stored)"""
    print("\n📋 Test 1b: Test connection with masked passwords")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Create payload with masked passwords
    masked_payload = {
        "from_name": "Damien",
        "from_email": "damien@intercloud-digital.com",
        "imap": {
            "host": "mail.intercloud-digital.com",
            "port": 993,
            "username": "damien@intercloud-digital.com",
            "password": "••••••••",
            "use_ssl": True
        },
        "smtp": {
            "host": "mail.intercloud-digital.com",
            "port": 465,
            "username": "damien@intercloud-digital.com",
            "password": "••••••••",
            "use_ssl": True
        }
    }
    
    resp = requests.post(f"{API_BASE}/settings/email/test", json=masked_payload, headers=headers)
    
    if resp.status_code != 200:
        log_test("Test connection with masked passwords", False, 
                f"Status {resp.status_code}: {resp.text}")
        return False
    
    data = resp.json()
    
    # Should succeed because it falls back to stored passwords
    if data.get("ok") == True and data.get("imap", {}).get("ok") == True and data.get("smtp", {}).get("ok") == True:
        log_test("Test connection with masked passwords - both protocols OK", True,
                f"IMAP: {data.get('imap', {}).get('message')}, SMTP: {data.get('smtp', {}).get('message')}")
        return True
    else:
        log_test("Test connection with masked passwords - both protocols OK", False,
                f"ok={data.get('ok')}, imap.ok={data.get('imap', {}).get('ok')}, smtp.ok={data.get('smtp', {}).get('ok')}")
        return False

def test_connection_with_real_passwords(token):
    """Test 1c: Test connection with real passwords"""
    print("\n📋 Test 1c: Test connection with real passwords")
    
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(f"{API_BASE}/settings/email/test", json=REAL_MAILBOX, headers=headers)
    
    if resp.status_code != 200:
        log_test("Test connection with real passwords", False,
                f"Status {resp.status_code}: {resp.text}")
        return False
    
    data = resp.json()
    
    if data.get("ok") == True and data.get("imap", {}).get("ok") == True and data.get("smtp", {}).get("ok") == True:
        log_test("Test connection with real passwords - both protocols OK", True,
                f"IMAP: {data.get('imap', {}).get('message')}, SMTP: {data.get('smtp', {}).get('message')}")
        return True
    else:
        log_test("Test connection with real passwords - both protocols OK", False,
                f"ok={data.get('ok')}, imap.ok={data.get('imap', {}).get('ok')}, smtp.ok={data.get('smtp', {}).get('ok')}")
        return False

def test_connection_with_wrong_passwords(token):
    """Test 1d: Test connection with wrong passwords (should return ok:false, NOT 5xx)"""
    print("\n📋 Test 1d: Test connection with wrong passwords")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    wrong_payload = {
        "from_name": "Damien",
        "from_email": "damien@intercloud-digital.com",
        "imap": {
            "host": "mail.intercloud-digital.com",
            "port": 993,
            "username": "damien@intercloud-digital.com",
            "password": "wrongpass123",
            "use_ssl": True
        },
        "smtp": {
            "host": "mail.intercloud-digital.com",
            "port": 465,
            "username": "damien@intercloud-digital.com",
            "password": "wrongpass123",
            "use_ssl": True
        }
    }
    
    resp = requests.post(f"{API_BASE}/settings/email/test", json=wrong_payload, headers=headers)
    
    # Should return 200 with ok:false, NOT a 5xx error
    if resp.status_code != 200:
        log_test("Test connection with wrong passwords - returns 200 (not 5xx)", False,
                f"Expected 200, got {resp.status_code}: {resp.text}")
        return False
    
    log_test("Test connection with wrong passwords - returns 200 (not 5xx)", True)
    
    data = resp.json()
    
    # Should have ok:false and both protocols should fail
    if data.get("ok") == False and data.get("imap", {}).get("ok") == False and data.get("smtp", {}).get("ok") == False:
        log_test("Test connection with wrong passwords - both protocols fail gracefully", True,
                f"IMAP: {data.get('imap', {}).get('message')}, SMTP: {data.get('smtp', {}).get('message')}")
        return True
    else:
        log_test("Test connection with wrong passwords - both protocols fail gracefully", False,
                f"ok={data.get('ok')}, imap.ok={data.get('imap', {}).get('ok')}, smtp.ok={data.get('smtp', {}).get('ok')}")
        return False

def test_send_email(token):
    """Test 2a: Send email with saved settings"""
    print("\n📋 Test 2a: Send email via POST /admin/mail/send")
    
    headers = {"Authorization": f"Bearer {token}"}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    payload = {
        "to": "damien@intercloud-digital.com",
        "subject": f"Backend test {timestamp}",
        "body": "<p>This is a test email from the backend test suite.</p>"
    }
    
    resp = requests.post(f"{API_BASE}/admin/mail/send", json=payload, headers=headers)
    
    if resp.status_code != 200:
        log_test("Send email with saved settings", False,
                f"Status {resp.status_code}: {resp.text}")
        return False
    
    data = resp.json()
    
    if data.get("delivered") == True and data.get("delivered_via") == "smtp":
        log_test("Send email with saved settings", True,
                f"Delivered via {data.get('delivered_via')} at {data.get('sent_at')}")
        return True
    else:
        log_test("Send email with saved settings", False,
                f"delivered={data.get('delivered')}, delivered_via={data.get('delivered_via')}")
        return False

def test_send_email_missing_fields(token):
    """Test 2b: Send email with missing to/subject (should return 400)"""
    print("\n📋 Test 2b: Send email with missing to/subject")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Missing 'to'
    resp = requests.post(f"{API_BASE}/admin/mail/send", json={"subject": "Test"}, headers=headers)
    if resp.status_code == 400:
        log_test("Send email missing 'to' returns 400", True)
    else:
        log_test("Send email missing 'to' returns 400", False, f"Got {resp.status_code}")
    
    # Missing 'subject'
    resp = requests.post(f"{API_BASE}/admin/mail/send", json={"to": "test@example.com"}, headers=headers)
    if resp.status_code == 400:
        log_test("Send email missing 'subject' returns 400", True)
    else:
        log_test("Send email missing 'subject' returns 400", False, f"Got {resp.status_code}")

def test_inbox_retrieval(token):
    """Test 3: GET /admin/mail/inbox - should contain the sent message"""
    print("\n📋 Test 3: Retrieve inbox via GET /admin/mail/inbox")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Wait a few seconds for email delivery
    print("   ⏳ Waiting 5 seconds for email delivery...")
    time.sleep(5)
    
    resp = requests.get(f"{API_BASE}/admin/mail/inbox", headers=headers)
    
    if resp.status_code != 200:
        log_test("Retrieve inbox", False, f"Status {resp.status_code}: {resp.text}")
        return False
    
    data = resp.json()
    
    # Check if it's a list (successful retrieval)
    if isinstance(data, list):
        log_test("Retrieve inbox - returns list", True, f"Found {len(data)} messages")
        
        # Look for our test message (sent in test 2a)
        found_test_message = False
        for msg in data:
            if "Backend test" in msg.get("subject", ""):
                found_test_message = True
                break
        
        if found_test_message:
            log_test("Retrieve inbox - contains sent test message", True)
        else:
            # Try one more time after another delay
            print("   ⏳ Test message not found, waiting 5 more seconds...")
            time.sleep(5)
            resp = requests.get(f"{API_BASE}/admin/mail/inbox", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for msg in data:
                        if "Backend test" in msg.get("subject", ""):
                            found_test_message = True
                            break
            
            if found_test_message:
                log_test("Retrieve inbox - contains sent test message (after retry)", True)
            else:
                log_test("Retrieve inbox - contains sent test message", False,
                        "Test message not found in inbox (may take longer to deliver)")
        
        return True
    elif isinstance(data, dict) and data.get("not_setup"):
        log_test("Retrieve inbox", False, f"Inbox not setup: {data.get('message')}")
        return False
    else:
        log_test("Retrieve inbox", False, f"Unexpected response format: {data}")
        return False

def test_edge_case_no_settings(token):
    """Test 4: User without email_settings"""
    print("\n📋 Test 4: Edge case - send email without SMTP settings")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # First, clear the admin's email settings
    print("   🧹 Temporarily clearing email settings...")
    resp = requests.delete(f"{API_BASE}/settings/email", headers=headers)
    
    if resp.status_code != 200:
        log_test("Clear email settings", False, f"Status {resp.status_code}: {resp.text}")
        return False
    
    log_test("Clear email settings", True)
    
    # Try to send email without settings
    payload = {
        "to": "damien@intercloud-digital.com",
        "subject": "Test without settings",
        "body": "<p>This should fail</p>"
    }
    
    resp = requests.post(f"{API_BASE}/admin/mail/send", json=payload, headers=headers)
    
    if resp.status_code == 400 and "Silakan setup SMTP" in resp.text:
        log_test("Send email without SMTP settings returns 400 with setup message", True,
                f"Error message: {resp.json().get('detail', resp.text)}")
    else:
        log_test("Send email without SMTP settings returns 400 with setup message", False,
                f"Status {resp.status_code}: {resp.text}")
    
    # Test connection endpoint with no stored settings and empty body
    resp = requests.post(f"{API_BASE}/settings/email/test", json={}, headers=headers)
    
    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok") == False:
            log_test("Test connection with no settings returns ok:false", True,
                    f"IMAP: {data.get('imap', {}).get('message')}, SMTP: {data.get('smtp', {}).get('message')}")
        else:
            log_test("Test connection with no settings returns ok:false", False,
                    f"Expected ok:false, got {data}")
    else:
        log_test("Test connection with no settings returns ok:false", False,
                f"Expected 200, got {resp.status_code}")
    
    # Restore settings for subsequent tests
    print("   🔄 Restoring email settings...")
    resp = requests.post(f"{API_BASE}/settings/email", json=REAL_MAILBOX, headers=headers)
    if resp.status_code == 200:
        log_test("Restore email settings", True)
    else:
        log_test("Restore email settings", False, f"Status {resp.status_code}")

def test_partial_update_with_masked_passwords(token):
    """Test 5: Regression - partial update with masked passwords"""
    print("\n📋 Test 5: Partial update - change from_name only, passwords masked")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Get current settings
    resp = requests.get(f"{API_BASE}/settings/email", headers=headers)
    if resp.status_code != 200:
        log_test("Get current email settings", False, f"Status {resp.status_code}")
        return False
    
    current = resp.json()
    log_test("Get current email settings", True)
    
    # Update only from_name, keep passwords masked
    update_payload = {
        "from_name": "Damien Updated",
        "from_email": current.get("from_email"),
        "imap": {
            "host": current.get("imap", {}).get("credentials", {}).get("host"),
            "port": current.get("imap", {}).get("credentials", {}).get("port"),
            "username": current.get("imap", {}).get("credentials", {}).get("username"),
            "password": current.get("imap", {}).get("credentials", {}).get("password"),  # masked
            "use_ssl": current.get("imap", {}).get("options", {}).get("use_ssl")
        },
        "smtp": {
            "host": current.get("smtp", {}).get("credentials", {}).get("host"),
            "port": current.get("smtp", {}).get("credentials", {}).get("port"),
            "username": current.get("smtp", {}).get("credentials", {}).get("username"),
            "password": current.get("smtp", {}).get("credentials", {}).get("password"),  # masked
            "use_ssl": current.get("smtp", {}).get("options", {}).get("use_ssl")
        }
    }
    
    resp = requests.post(f"{API_BASE}/settings/email", json=update_payload, headers=headers)
    
    if resp.status_code != 200:
        log_test("Partial update with masked passwords", False, f"Status {resp.status_code}: {resp.text}")
        return False
    
    data = resp.json()
    
    # Verify from_name was updated
    if data.get("from_name") == "Damien Updated":
        log_test("Partial update - from_name updated", True)
    else:
        log_test("Partial update - from_name updated", False, f"Got: {data.get('from_name')}")
        return False
    
    # Verify configured flag is still true
    if data.get("configured") == True:
        log_test("Partial update - configured flag still true", True)
    else:
        log_test("Partial update - configured flag still true", False, f"configured={data.get('configured')}")
        return False
    
    # Verify we can still test connection (passwords should be preserved)
    resp = requests.post(f"{API_BASE}/settings/email/test", json={}, headers=headers)
    
    if resp.status_code == 200:
        data = resp.json()
        if data.get("ok") == True:
            log_test("Partial update - connection still works after update", True)
        else:
            log_test("Partial update - connection still works after update", False,
                    f"Connection test failed: {data}")
    else:
        log_test("Partial update - connection still works after update", False,
                f"Status {resp.status_code}")
    
    # Restore original from_name
    restore_payload = dict(update_payload)
    restore_payload["from_name"] = "Damien"
    requests.post(f"{API_BASE}/settings/email", json=restore_payload, headers=headers)

def print_summary():
    """Print test summary"""
    print("\n" + "="*80)
    print("📊 TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for t in test_results if t["passed"])
    total = len(test_results)
    
    print(f"\nTotal tests: {total}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {total - passed} ❌")
    
    if failed_tests:
        print("\n❌ FAILED TESTS:")
        for test in failed_tests:
            print(f"  • {test['name']}")
            if test['details']:
                print(f"    {test['details']}")
    else:
        print("\n🎉 ALL TESTS PASSED!")
    
    print("\n" + "="*80)

def main():
    """Main test runner"""
    print("="*80)
    print("🧪 INTERCLOUD PORTAL WEBMAIL BACKEND TESTS")
    print("="*80)
    
    # Test unauthenticated access first
    test_unauthenticated_access()
    
    # Login
    token = login_admin()
    if not token:
        print("\n❌ Cannot proceed without admin token")
        print_summary()
        sys.exit(1)
    
    # Run all tests
    test_save_email_settings(token)
    test_connection_with_masked_passwords(token)
    test_connection_with_real_passwords(token)
    test_connection_with_wrong_passwords(token)
    test_send_email(token)
    test_send_email_missing_fields(token)
    test_inbox_retrieval(token)
    test_edge_case_no_settings(token)
    test_partial_update_with_masked_passwords(token)
    
    # Print summary
    print_summary()
    
    # Exit with appropriate code
    if failed_tests:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
