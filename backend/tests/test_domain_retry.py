"""Tests for domain retry-registration and customer fallback logic."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

sys.path.insert(0, "/home/support/INTERCLOUD/backend")


def _mock_user(**overrides):
    base = {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "081234567890",
        "company": "PT Test",
        "address_line1": "Jl. Test No. 1",
        "address_line2": "",
        "city": "Jakarta",
        "province": "DKI Jakarta",
        "postal_code": "12345",
        "country": "Indonesia",
    }
    base.update(overrides)
    return base


def _mock_domain(**overrides):
    base = {
        "_id": ObjectId(),
        "domain": "testdomain.my.id",
        "tld": ".my.id",
        "status": "pending",
        "registrar": "rna",
        "years": 1,
        "user_id": ObjectId(),
        "price": 200000,
        "nameservers": [],
        "created_at": "2026-08-09T00:00:00+00:00",
    }
    base.update(overrides)
    return base


class TestResolveRnaCustomerFallback:
    """_resolve_rna_customer must always return a customer_id, never raise."""

    def test_incomplete_profile_uses_integration_customer_id(self):
        """When user profile is incomplete AND rna.customer_id is set,
        fallback should use rna.customer_id, not hardcoded 35284."""
        from portal.routes.domains import _resolve_rna_customer

        async def run():
            db = MagicMock()
            db.users = MagicMock()
            db.users.find_one = AsyncMock(return_value=_mock_user(name="", email="", phone="", company="", address_line1="", city="", province="", postal_code=""))

            rna = MagicMock()
            rna.customer_id = "99999"
            rna.list_customers = AsyncMock(return_value=[])

            result = await _resolve_rna_customer(db, rna, str(ObjectId()))
            assert result["customer_id"] == "99999"
            assert result["fallback"] is True
            assert result["reason"] == "integration_customer_id"

        asyncio.run(run())

    def test_incomplete_profile_hardcoded_fallback(self):
        """When profile is incomplete AND no rna.customer_id, fall back to 35284."""
        from portal.routes.domains import _resolve_rna_customer

        async def run():
            db = MagicMock()
            db.users = MagicMock()
            db.users.find_one = AsyncMock(return_value=_mock_user(name="", email="", phone="", company="", address_line1="", city="", province="", postal_code=""))

            rna = MagicMock()
            rna.customer_id = ""
            rna.list_customers = AsyncMock(return_value=[])

            result = await _resolve_rna_customer(db, rna, str(ObjectId()))
            assert result["customer_id"] == "35284"
            assert result["fallback"] is True

        asyncio.run(run())

    def test_create_failed_uses_integration_customer_id(self):
        """When customer creation fails AND rna.customer_id is set,
        fallback should use rna.customer_id."""
        from portal.routes.domains import _resolve_rna_customer

        async def run():
            db = MagicMock()
            db.users = MagicMock()
            db.users.find_one = AsyncMock(return_value=_mock_user())

            rna = MagicMock()
            rna.customer_id = "88888"
            rna.list_customers = AsyncMock(return_value=[])
            rna.create_customer = AsyncMock(side_effect=RuntimeError("RDASH 422: customer_id required"))

            result = await _resolve_rna_customer(db, rna, str(ObjectId()))
            assert result["customer_id"] == "88888"
            assert result["fallback"] is True
            assert "integration_customer_id" in result["reason"]

        asyncio.run(run())

    def test_existing_customer_no_fallback(self):
        """When an existing customer is found by email, no fallback needed."""
        from portal.routes.domains import _resolve_rna_customer

        async def run():
            db = MagicMock()
            db.users = MagicMock()
            db.users.find_one = AsyncMock(return_value=_mock_user())

            rna = MagicMock()
            rna.customer_id = "99999"
            rna.list_customers = AsyncMock(return_value=[{"id": "12345"}])

            result = await _resolve_rna_customer(db, rna, str(ObjectId()))
            assert result["customer_id"] == "12345"
            assert result["fallback"] is False
            assert result["reason"] == "existing"

        asyncio.run(run())


class TestProvisionDomainRegistration:
    """_provision_domain_registration must handle pending status and errors."""

    def test_non_pending_skipped(self):
        from portal.routes.domains import _provision_domain_registration

        async def run():
            db = MagicMock()
            dom = _mock_domain(status="active")
            result = await _provision_domain_registration(db, dom)
            assert result["ok"] is False
            assert result["skipped"] is True

        asyncio.run(run())

    def test_rna_register_success(self):
        from portal.routes.domains import _provision_domain_registration

        async def run():
            db = MagicMock()
            db.domains = MagicMock()
            db.domains.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

            dom = _mock_domain()

            with patch("portal.routes.domains._rna_client", new_callable=AsyncMock) as mock_rna_client:
                rna = MagicMock()
                rna.default_ns = ["ns1.test.com", "ns2.test.com"]
                rna.register = AsyncMock(return_value={
                    "id": "order-123",
                    "expired_at": "2027-08-09",
                    "nameserver_1": "ns1.test.com",
                    "nameserver_2": "ns2.test.com",
                })
                mock_rna_client.return_value = rna

                with patch("portal.routes.domains._resolve_rna_customer", new_callable=AsyncMock) as mock_resolve:
                    mock_resolve.return_value = {"customer_id": "12345", "fallback": False, "reason": "existing"}
                    result = await _provision_domain_registration(db, dom)

            assert result["ok"] is True
            assert result["customer_id"] == "12345"
            assert result["fallback"] is False

        asyncio.run(run())

    def test_rna_register_failure_stays_pending(self):
        from portal.routes.domains import _provision_domain_registration

        async def run():
            db = MagicMock()
            db.domains = MagicMock()
            db.domains.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

            dom = _mock_domain()

            with patch("portal.routes.domains._rna_client", new_callable=AsyncMock) as mock_rna_client:
                rna = MagicMock()
                rna.default_ns = ["ns1.test.com"]
                rna.register = AsyncMock(side_effect=RuntimeError("RDASH 422: customer_id required"))
                mock_rna_client.return_value = rna

                with patch("portal.routes.domains._resolve_rna_customer", new_callable=AsyncMock) as mock_resolve:
                    mock_resolve.return_value = {"customer_id": "35284", "fallback": True, "reason": "fallback"}
                    result = await _provision_domain_registration(db, dom)

            assert result["ok"] is False
            assert "error" in result

        asyncio.run(run())
