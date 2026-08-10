"""Source-level contract tests for the transaction ledger.

These tests are intentionally dependency-free so route/RBAC wiring can be checked
without a running MongoDB service. Integration behavior remains covered separately.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "portal" / "routes"


class TransactionLedgerContractTest(unittest.TestCase):
    def test_summary_route_precedes_dynamic_detail_route(self):
        source = (ROUTES / "transactions.py").read_text()
        self.assertIn('@router.get("/admin/transactions/summary")', source)
        self.assertLess(
            source.index('@router.get("/admin/transactions/summary")'),
            source.index('@router.get("/admin/transactions/{tid}")'),
            "summary must be registered before /{tid} to avoid route shadowing",
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


if __name__ == "__main__":
    unittest.main()
