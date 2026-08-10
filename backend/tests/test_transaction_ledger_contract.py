"""Source-level contract tests for the transaction ledger.

These tests are intentionally dependency-free so route/RBAC wiring can be checked
without a running MongoDB service. Integration behavior remains covered separately.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "portal" / "routes"
MODELS = ROOT / "portal" / "models.py"
FRONTEND = ROOT.parent / "frontend" / "src" / "pages" / "portal" / "admin" / "AdminTransactions.jsx"


class TransactionLedgerContractTest(unittest.TestCase):
    def test_summary_route_precedes_dynamic_detail_route(self):
        source = (ROUTES / "transactions.py").read_text()
        self.assertIn('@router.get("/admin/transactions/summary")', source)
        self.assertLess(
            source.index('@router.get("/admin/transactions/summary")'),
            source.index('@router.get("/admin/transactions/{tid}")'),
            "summary must be registered before /{tid} to avoid route shadowing",
        )

    def test_xlsx_export_route_precedes_dynamic_detail_route(self):
        source = (ROUTES / "transactions.py").read_text()
        self.assertIn('@router.get("/admin/transactions/export/xlsx")', source)
        self.assertLess(
            source.index('@router.get("/admin/transactions/export/xlsx")'),
            source.index('@router.get("/admin/transactions/{tid}")'),
            "export/xlsx must be registered before /{tid} to avoid route shadowing",
        )

    def test_summary_and_lists_are_sales_scoped(self):
        source = (ROUTES / "transactions.py").read_text()
        tree = ast.parse(source)
        functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in ("list_transactions", "transaction_summary"):
            self.assertIn(name, functions)
            body = ast.get_source_segment(source, functions[name]) or ""
            self.assertIn('_sales_scope_filter(staff, key="user_id")', body)
            self.assertIn('require_roles("admin", "finance", "sales")', body)

    def test_list_transaction_accepts_filter_params(self):
        source = (ROUTES / "transactions.py").read_text()
        tree = ast.parse(source)
        func = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "list_transactions"][0]
        func_src = ast.get_source_segment(source, func) or ""
        for param in ("search", "status", "method", "start", "end"):
            self.assertIn(param, func_src, f"list_transactions missing filter param: {param}")

    def test_serializer_includes_verified_fields(self):
        source = (ROUTES / "transactions.py").read_text()
        tree = ast.parse(source)
        func = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_serialize_transaction"][0]
        func_src = ast.get_source_segment(source, func) or ""
        self.assertIn('"verified"', func_src, "serializer missing 'verified' key")
        self.assertIn('"verified_by"', func_src, "serializer missing 'verified_by' key")

    def test_xlsx_export_uses_openpyxl(self):
        source = (ROUTES / "transactions.py").read_text()
        tree = ast.parse(source)
        func = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "export_transactions"][0]
        func_src = ast.get_source_segment(source, func) or ""
        self.assertIn("openpyxl", func_src, "export function should use openpyxl")
        self.assertIn("StreamingResponse", func_src, "export should return StreamingResponse")

    def test_invoice_paid_paths_write_ledger_events(self):
        source = (ROUTES / "billing.py").read_text()
        tree = ast.parse(source)
        functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in ("admin_update_invoice_status", "payment_webhook"):
            body = ast.get_source_segment(source, functions[name]) or ""
            self.assertIn("_log_transaction", body)

    def test_router_is_mounted(self):
        source = (ROUTES / "__init__.py").read_text()
        self.assertIn("transactions", source)
        self.assertIn("router.include_router(transactions.router)", source)

    def test_invoice_preview_is_sales_scoped(self):
        """Invoice preview/download must restrict sales to assigned clients' invoices."""
        source = (ROUTES / "documents.py").read_text()
        tree = ast.parse(source)
        func = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "render_invoice_pdf"][0]
        func_src = ast.get_source_segment(source, func) or ""
        self.assertIn("_sales_scope_filter", func_src, "invoice preview must apply sales scope")
        self.assertIn('role") == "sales"', func_src, "invoice preview must branch on sales role")
        self.assertIn('"Not your client\'s invoice"', func_src, "invoice preview must 403 for unassigned clients")

    def test_model_has_verified_fields(self):
        source = MODELS.read_text()
        tree = ast.parse(source)
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TransactionOut"]
        self.assertTrue(classes, "TransactionOut model not found")
        cls_src = ast.get_source_segment(source, classes[0]) or ""
        self.assertIn("verified", cls_src)
        self.assertIn("verified_by", cls_src)


class TransactionLedgerFrontendContractTest(unittest.TestCase):
    """Source-level checks that the frontend JSX references the required features."""

    @classmethod
    def setUpClass(cls):
        cls.jsx = FRONTEND.read_text()

    def test_filter_elements_present(self):
        self.assertIn("tx-filter-status", self.jsx, "status filter missing")
        self.assertIn("tx-filter-method", self.jsx, "method filter missing")
        self.assertIn("tx-filter-start", self.jsx, "date start filter missing")
        self.assertIn("tx-filter-end", self.jsx, "date end filter missing")
        self.assertIn("tx-search", self.jsx, "search input missing")

    def test_invoice_preview_button_present(self):
        self.assertIn("setPreviewId", self.jsx, "no invoice preview logic")
        self.assertIn("tx-preview-", self.jsx, "no invoice preview test id")
        self.assertIn("tx-pdf-", self.jsx, "no invoice PDF download test id")

    def test_export_xlsx_button_present(self):
        self.assertIn("tx-export-xlsx", self.jsx, "export XLSX button missing")
        self.assertIn("/admin/transactions/export/xlsx", self.jsx, "export API call missing")

    def test_reference_column_present(self):
        self.assertIn('"reference"', self.jsx, "reference column missing")

    def test_verified_column_present(self):
        self.assertIn('"verified"', self.jsx, "verified column missing")
        # Check the verified column render does NOT use "pending" as a label
        # (the old UI showed "pending" instead of "—" for unverified rows)
        verified_col_block = self.jsx.split('key: "verified"')[1].split("},{")[0]
        self.assertNotIn('"pending"', verified_col_block,
                         "verified column should not label unverified rows as 'pending'")

    def test_summary_cards_present(self):
        self.assertIn("paid_amount", self.jsx)
        self.assertIn("outstanding_amount", self.jsx)


if __name__ == "__main__":
    unittest.main()
