"""AST-level contract tests - no DB, no network."""
import ast, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

CATALOG = pathlib.Path(__file__).resolve().parent.parent / "portal" / "routes" / "catalog.py"
SRC = CATALOG.read_text()
TREE = ast.parse(SRC)

router_funcs = {}
for node in ast.walk(TREE):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for dec in node.decorator_list:
        # dec is a Call; dec.func is either Name (unlikely) or Attribute (router.post)
        meth = None
        if isinstance(dec.func, ast.Attribute):
            meth = dec.func.attr                 # "post", "get", ...
        elif isinstance(dec.func, ast.Name):
            meth = dec.func.id
        if meth not in {"get","post","put","delete"}:
            continue
        path = dec.args[0].value if dec.args else ""
        router_funcs.setdefault(node.name, []).append((meth.upper(), path))

REQUIRED = {
    "form_builder_create":        [("POST", "/admin/form-builder")],
    "form_builder_update":        [("PUT", "/admin/form-builder/{fid}")],
    "form_builder_publish":       [("PUT", "/admin/form-builder/{fid}/publish")],
    "form_builder_new_draft":     [("PUT", "/admin/form-builder/{fid}/draft")],
    "public_form_config":         [("GET", "/portal-public/forms/{identifier}")],
    "public_form_submit":         [("POST", "/portal-public/forms/{identifier}/submit")],
    "form_builder_export":        [("GET", "/admin/form-builder/{fid}/export")],
}

def test_all_required_endpoints_exist():
    for fn, specs in REQUIRED.items():
        assert fn in router_funcs, f"missing function {fn}"
        for method, path in specs:
            assert (method, path) in router_funcs[fn], f"{fn} missing {method} {path}"

MUTATING = {"form_builder_create","form_builder_update","form_builder_publish",
            "form_builder_new_draft","form_builder_export"}

def test_mutating_endpoints_use_staff_dependency():
    for fn in MUTATING:
        func_node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
        args = func_node.args
        # defaults are aligned to the tail of args.args
        defaults = args.defaults
        found = False
        for d in defaults:
            if isinstance(d, ast.Call) and (getattr(d.func, "attr", "") == "Depends" or getattr(d.func, "id", "") == "Depends"):
                if any(getattr(a, "id", "") == "get_current_staff" for a in d.args):
                    found = True
                    break
        assert found, f"{fn} missing staff dependency"

def test_public_endpoint_no_staff_dep():
    fn = "public_form_config"
    func_node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
    args = func_node.args
    defaults = args.defaults
    has_staff = False
    for d in defaults:
        if isinstance(d, ast.Call) and (getattr(d.func, "attr", "") == "Depends" or getattr(d.func, "id", "") == "Depends"):
            if any(getattr(a, "id", "") == "get_current_staff" for a in d.args):
                has_staff = True
                break
    assert not has_staff, "public_form_config must be unauthenticated"
