"""AST contract tests for chat routes — no DB, no network."""
import ast, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

CHAT_ROUTES = pathlib.Path(__file__).resolve().parents[1] / "portal" / "routes" / "chat.py"
SRC = CHAT_ROUTES.read_text()
TREE = ast.parse(SRC)

router_funcs = {}
for node in ast.walk(TREE):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for dec in node.decorator_list:
        meth = None
        if isinstance(dec.func, ast.Attribute):
            meth = dec.func.attr
        elif isinstance(dec.func, ast.Name):
            meth = dec.func.id
        if meth not in {"get", "post", "put", "delete"}:
            continue
        path = dec.args[0].value if dec.args else ""
        router_funcs.setdefault(node.name, []).append((meth.upper(), path))

REQUIRED = {
    "chat_config_get": [("GET", "/chat/config")],
    "chat_config_set": [("POST", "/admin/chat/config")],
}

def test_all_required_endpoints_exist():
    for fn, specs in REQUIRED.items():
        assert fn in router_funcs, f"missing function {fn}"
        for method, path in specs:
            assert (method, path) in router_funcs[fn], f"{fn} missing {method} {path}"

def test_public_endpoint_no_admin_dependency():
    fn = "chat_config_get"
    func_node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
    for d in func_node.args.defaults:
        if isinstance(d, ast.Call) and (getattr(d.func, "attr", "") == "Depends" or getattr(d.func, "id", "") == "Depends"):
            for a in d.args:
                if getattr(a, "id", "") == "get_current_admin":
                    raise AssertionError("chat_config_get must be public (no admin dependency)")

def test_admin_endpoint_has_admin_dependency():
    fn = "chat_config_set"
    func_node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
    has_admin = False
    for d in func_node.args.defaults:
        if isinstance(d, ast.Call) and (getattr(d.func, "attr", "") == "Depends" or getattr(d.func, "id", "") == "Depends"):
            for a in d.args:
                if getattr(a, "id", "") == "get_current_admin":
                    has_admin = True
    assert has_admin, "chat_config_set must require admin dependency"

def test_chat_config_model_exists():
    model_found = any(isinstance(n, ast.ClassDef) and n.name == "ChatConfigIn" for n in ast.walk(TREE))
    assert model_found, "ChatConfigIn model not found"

def test_defaults_defined():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", "") == "CHAT_DEFAULTS":
                    assert isinstance(node.value, ast.Dict)
                    keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                    assert "enabled" in keys
                    assert "widget_id" in keys
                    assert "api_base" in keys
                    return
    raise AssertionError("CHAT_DEFAULTS not found")

def test_router_registered_in_init():
    INIT = pathlib.Path(__file__).resolve().parents[1] / "portal" / "routes" / "__init__.py"
    init_src = INIT.read_text()
    assert "chat" in init_src, "chat not imported in __init__.py"
    assert "chat.router" in init_src, "chat.router not included"
