"""Product catalog v2 (option-groups + add-ons + categories) + order-preview cart tests."""
import os
import time
import requests
import pytest

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def tokens():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"],
    })
    r.raise_for_status()
    admin = r.json()["token"]
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["CLIENT_EMAIL"], "password": os.environ["CLIENT_PASSWORD"],
    })
    r.raise_for_status()
    client = r.json()["token"]
    return {"admin": admin, "client": client}


class TestCategories:
    def test_default_categories_seeded(self, tokens):
        r = requests.get(f"{API}/admin/categories", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        rows = r.json()
        slugs = {c["slug"] for c in rows}
        for expected in ("cloud", "vps", "hosting", "dedicated", "colocation", "firewall", "interconnect"):
            assert expected in slugs

    def test_public_categories_endpoint(self):
        r = requests.get(f"{API}/portal-public/categories")
        assert r.status_code == 200
        assert len(r.json()) >= 5

    def test_create_and_delete_category(self, tokens):
        slug = f"testcat_{int(time.time())}"
        r = requests.post(f"{API}/admin/categories", headers=_h(tokens["admin"]),
                          json={"slug": slug, "label": "Test Cat", "sort_order": 500})
        assert r.status_code == 200
        cid = r.json()["id"]
        # Duplicate slug rejected
        r2 = requests.post(f"{API}/admin/categories", headers=_h(tokens["admin"]),
                           json={"slug": slug, "label": "Dup"})
        assert r2.status_code == 409
        # Delete
        r3 = requests.delete(f"{API}/admin/categories/{cid}", headers=_h(tokens["admin"]))
        assert r3.status_code == 200


class TestProductOptions:
    """Create a fully-configurable product + add-on, then price the cart."""

    @pytest.fixture(scope="class")
    def sample(self, tokens):
        # Base product with 2 option groups (dropdown + quantity)
        r = requests.post(f"{API}/admin/products", headers=_h(tokens["admin"]), json={
            "name": f"Pytest VPS {int(time.time())}",
            "category": "vps",
            "description": "Test product with options",
            "price_monthly": 100000,
            "setup_fee": 0,
            "features": ["Test feature 1"],
            "is_active": True,
            "is_addon": False,
            "option_groups": [
                {"key": "ram", "label": "RAM", "type": "dropdown", "required": True, "options": [
                    {"label": "2 GB", "price_monthly_delta": 0, "is_default": True},
                    {"label": "8 GB", "price_monthly_delta": 150000},
                ]},
                {"key": "ips", "label": "Extra IPs", "type": "quantity", "required": False,
                 "min_qty": 0, "max_qty": 5, "unit_label": "IP", "unit_price_monthly": 25000},
            ],
        })
        assert r.status_code == 200, r.text
        product = r.json()

        # Add-on that attaches to the vps category
        r2 = requests.post(f"{API}/admin/products", headers=_h(tokens["admin"]), json={
            "name": f"Pytest Backup {int(time.time())}",
            "category": "other",
            "price_monthly": 50000,
            "is_addon": True,
            "applies_to_categories": ["vps"],
        })
        assert r2.status_code == 200
        addon = r2.json()

        yield product, addon

        requests.delete(f"{API}/admin/products/{product['id']}", headers=_h(tokens["admin"]))
        requests.delete(f"{API}/admin/products/{addon['id']}", headers=_h(tokens["admin"]))

    def test_product_persists_option_groups(self, sample):
        product, _ = sample
        assert len(product["option_groups"]) == 2
        assert product["option_groups"][0]["key"] == "ram"
        assert product["option_groups"][1]["type"] == "quantity"

    def test_addon_flag_persisted_and_appears_in_public_endpoint(self, sample):
        _, addon = sample
        assert addon["is_addon"] is True
        r = requests.get(f"{API}/portal-public/addons")
        addon_ids = {a["id"] for a in r.json()}
        assert addon["id"] in addon_ids
        # And is EXCLUDED from public /products
        r2 = requests.get(f"{API}/portal-public/products")
        base_ids = {p["id"] for p in r2.json()}
        assert addon["id"] not in base_ids

    def test_order_preview_prices_correctly(self, tokens, sample):
        product, addon = sample
        r = requests.post(f"{API}/orders/preview", headers=_h(tokens["client"]), json={
            "product_id": product["id"],
            "selections": [
                {"group_key": "ram", "option_labels": ["8 GB"]},
                {"group_key": "ips", "quantity": 2},
            ],
            "addon_ids": [addon["id"]],
        })
        assert r.status_code == 200
        cart = r.json()
        # 100k base + 150k RAM + (2 × 25k) IPs + 50k addon = 350k/mo
        assert cart["subtotal_monthly"] == 350000
        assert cart["setup_total"] == 0
        assert cart["subtotal"] == 350000
        # 11 % tax
        assert cart["tax_amount"] == pytest.approx(38500, rel=0.001)
        assert cart["total"] == pytest.approx(388500, rel=0.001)
        # Option lines shape check
        assert len(cart["option_lines"]) == 2
        assert cart["option_lines"][0]["group_key"] == "ram"
        assert cart["addon_lines"][0]["id"] == addon["id"]

    def test_order_preview_with_no_selections_uses_only_base(self, tokens, sample):
        product, _ = sample
        r = requests.post(f"{API}/orders/preview", headers=_h(tokens["client"]),
                          json={"product_id": product["id"]})
        assert r.status_code == 200
        cart = r.json()
        assert cart["subtotal_monthly"] == 100000
        # 100k * 1.11 = 111000
        assert cart["total"] == pytest.approx(111000, rel=0.001)

    def test_order_creation_snapshots_cart(self, tokens, sample):
        product, addon = sample
        r = requests.post(f"{API}/client/orders", headers=_h(tokens["client"]), json={
            "product_id": product["id"],
            "selections": [{"group_key": "ram", "option_labels": ["8 GB"]}],
            "addon_ids": [addon["id"]],
            "notes": "pytest order",
        })
        assert r.status_code == 200
        order = r.json()
        # Invoice was auto-created
        assert order.get("invoice_id")

    def test_addon_cannot_be_ordered_directly(self, tokens, sample):
        _, addon = sample
        r = requests.post(f"{API}/orders/preview", headers=_h(tokens["client"]),
                          json={"product_id": addon["id"]})
        assert r.status_code == 404


class TestUserAccessCatalog:
    def test_catalog_returns_menu_and_flags(self, tokens):
        r = requests.get(f"{API}/admin/user-access-catalog", headers=_h(tokens["admin"]))
        assert r.status_code == 200
        body = r.json()
        assert "menu_catalog" in body and "feature_flags" in body
        assert len(body["menu_catalog"]) >= 20
        assert len(body["feature_flags"]) >= 5
        # Each menu item has key/label/group/default_roles
        for m in body["menu_catalog"]:
            assert set(m.keys()) >= {"key", "label", "group", "default_roles"}

    def test_client_cannot_read_catalog(self, tokens):
        r = requests.get(f"{API}/admin/user-access-catalog", headers=_h(tokens["client"]))
        assert r.status_code == 403

    def test_update_user_menu_keys_and_flags(self, tokens):
        # Pick any non-admin staff user
        r = requests.get(f"{API}/admin/users", headers=_h(tokens["admin"]))
        u = next(x for x in r.json() if x["role"] == "sales")
        r2 = requests.put(f"{API}/admin/users/{u['id']}", headers=_h(tokens["admin"]), json={
            "menu_keys": ["dashboard", "orders", "tickets"],
            "feature_flags": ["can_export_data"],
        })
        assert r2.status_code == 200
        body = r2.json()
        assert set(body["menu_keys"]) == {"dashboard", "orders", "tickets"}
        assert "can_export_data" in body["feature_flags"]
        # Reset
        requests.put(f"{API}/admin/users/{u['id']}", headers=_h(tokens["admin"]),
                     json={"menu_keys": [], "feature_flags": []})
