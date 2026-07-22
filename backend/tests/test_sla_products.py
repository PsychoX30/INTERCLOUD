"""
Bug 2 verification: ensure no product `features` string contains
99.9% / 99.95% / 99.99% / 99,9% / 99,95% / 99,99% either on the
admin endpoint or the public products endpoint.
"""
import os
import re
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fall back to frontend/.env if not exported in process env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

ADMIN_EMAIL = "admin@intercloud-digital.com"
ADMIN_PASSWORD = "AdminIntercloud2026!"

BAD_PATTERN = re.compile(r"99[.,](?:9|95|99)%")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/portal/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "token" in data
    return data["token"]


def _assert_no_bad_sla(products, source_name):
    hits = []
    for p in products:
        for f in p.get("features") or []:
            if isinstance(f, str) and BAD_PATTERN.search(f):
                hits.append({"product": p.get("name"), "feature": f})
    assert not hits, f"[{source_name}] Found stale SLA values: {hits}"


def test_admin_products_no_stale_sla(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/portal/admin/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    products = r.json()
    assert isinstance(products, list) and len(products) > 0, "No products returned"
    _assert_no_bad_sla(products, "admin/products")


def test_public_products_no_stale_sla():
    r = requests.get(f"{BASE_URL}/api/portal/portal-public/products", timeout=15)
    assert r.status_code == 200, f"Status {r.status_code}: {r.text}"
    products = r.json()
    assert isinstance(products, list) and len(products) > 0, "No products returned"
    _assert_no_bad_sla(products, "public products")


def test_dc_to_dc_product_has_99_5_sla(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/portal/admin/products",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    )
    assert r.status_code == 200
    products = r.json()
    dc = next((p for p in products if p.get("name") == "DC-to-DC 100 Mbps"), None)
    assert dc is not None, "DC-to-DC 100 Mbps product missing"
    features = dc.get("features") or []
    sla_lines = [f for f in features if "SLA" in f or "%" in f]
    assert any("99.5" in f or "99,5" in f for f in sla_lines), \
        f"DC-to-DC product does not contain 99.5% SLA feature: {sla_lines}"
