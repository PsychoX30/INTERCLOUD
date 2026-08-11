"""Regression: uploaded business documents must never be public by ObjectId."""
from __future__ import annotations

import ast
from pathlib import Path


BUSINESS_ROUTE = Path(__file__).parents[1] / "portal" / "routes" / "business.py"


def test_uploaded_business_document_download_requires_staff_authentication():
    """The file endpoint must require staff auth; ObjectId is not authorization."""
    tree = ast.parse(BUSINESS_ROUTE.read_text())
    handler = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "docs_file"
    )

    dependency_defaults = [
        default for default in handler.args.defaults
        if isinstance(default, ast.Call)
        and isinstance(default.func, ast.Name)
        and default.func.id == "Depends"
    ]
    assert any(
        isinstance(dependency.args[0], ast.Name)
        and dependency.args[0].id == "get_current_staff"
        for dependency in dependency_defaults
    ), "docs_file must declare Depends(get_current_staff)"
