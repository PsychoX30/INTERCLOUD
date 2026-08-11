"""Source contract for sales-safe CRM UI wiring."""
from pathlib import Path


CRM = Path(__file__).resolve().parents[2] / "frontend/src/pages/portal/admin/AdminBusiness.jsx"


def test_sales_crm_ui_uses_auth_context_and_assigned_clients():
    source = CRM.read_text()
    assert 'import { useAuth } from "../../../portal/AuthContext";' in source
    assert "const isSales = user?.role?.toLowerCase() === \"sales\";" in source
    assert 'api.get("/admin/users")' in source
    assert "clients={clients}" in source
    assert "isSales={isSales}" in source
    assert "!isSales &&" in source
    # Sales form picks a client from the dropdown whose option value is a user_id
    assert 'data-testid="crm-client"' in source
    assert '<option key={u.id} value={u.id}>' in source
