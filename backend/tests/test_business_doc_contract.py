"""Source-level contract tests for business document security.

Dependency-free AST checks verifying that business document endpoints are
not public and follow staff authentication patterns.
"""
from pathlib import Path
import ast
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "portal" / "routes"


class BusinessDocumentContractTest(unittest.TestCase):
    def test_docs_file_requires_staff_auth(self):
        """GET /documents/file/{did} must require staff authentication; it is not public."""
        source = (ROUTES / "business.py").read_text()
        tree = ast.parse(source)
        funcs = {
            n.name: n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertIn("docs_file", funcs, "docs_file handler not found")
        func = funcs["docs_file"]
        func_src = ast.get_source_segment(source, func) or ""

        # Must not be a public endpoint (no auth dependency = public)
        self.assertNotIn("async def docs_file(did: str):", func_src,
                         "docs_file is declared without an auth dependency")

        # Must depend on one of the staff/admin auth guards
        self.assertTrue(
            "get_current_staff" in func_src or "get_current_admin" in func_src,
            "docs_file must depend on get_current_staff or get_current_admin",
        )

        # Router path must remain as the public-ish URL pattern (business contract)
        decorators = [
            d for d in func.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
        ]
        paths = []
        for d in decorators:
            for kw in d.keywords:
                if kw.arg == "path" and isinstance(kw.value, ast.Constant):
                    paths.append(kw.value.value)
            for arg in d.args:
                if isinstance(arg, ast.Constant):
                    paths.append(arg.value)
        self.assertIn("/documents/file/{did}", paths,
                      "docs_file route path must be /documents/file/{did}")

    def test_document_ui_uses_authenticated_blob_download(self):
        """Opening a protected file must use the Axios auth interceptor, not a raw URL."""
        frontend = ROOT.parent / "frontend" / "src" / "pages" / "portal" / "admin" / "AdminBusiness.jsx"
        source = frontend.read_text()
        # api has baseURL /api/portal, so use a relative API path assembled
        # from trusted API fields rather than stored absolute/prefixed URLs.
        self.assertIn('`/documents/file/${d.id}`', source)
        self.assertIn('api.get(path, { responseType: "blob" })', source)
        self.assertIn("URL.createObjectURL", source)
        self.assertIn('d.has_file && d.id ? (', source)
        # Arbitrary external document URLs must never receive the portal bearer
        # token through Axios; those remain ordinary browser navigation.
        self.assertIn('href={d.url} target="_blank"', source)

    def test_documents_nav_excludes_sales(self):
        """Sales is denied document operations until client-level ownership exists."""
        layout = ROOT.parent / "frontend" / "src" / "pages" / "portal" / "PortalLayout.jsx"
        source = layout.read_text()
        line = next(line for line in source.splitlines() if 'key: "documents"' in line)
        self.assertNotIn('"sales"', line)


if __name__ == "__main__":
    unittest.main()
