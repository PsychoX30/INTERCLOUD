"""AST contract tests for jitsi routes — no DB, no network."""
import ast, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

JITSI_ROUTES = pathlib.Path(__file__).resolve().parents[1] / "portal" / "routes" / "jitsi.py"
SRC = JITSI_ROUTES.read_text()
TREE = ast.parse(SRC)

router_funcs = {}
for node in ast.walk(TREE):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for dec in node.decorator_list:
        # Defensive: decorator bisa berupa ast.Name (@classmethod/@staticmethod)
        # atau ast.Call (@router.get("/x")) — jangan asumsikan punya `.func`.
        meth = None
        target = getattr(dec, "func", None)
        if isinstance(target, ast.Attribute):
            meth = target.attr
        elif isinstance(target, ast.Name):
            meth = target.id
        if meth not in {"get", "post", "put", "delete"}:
            continue
        if not isinstance(dec, ast.Call):
            continue
        path = dec.args[0].value if dec.args else ""
        router_funcs.setdefault(node.name, []).append((meth.upper(), path))

REQUIRED = {
    "jitsi_config_get": [("GET", "/jitsi/config")],
    "jitsi_config_set": [("POST", "/admin/jitsi/config")],
}

def test_all_required_endpoints_exist():
    for fn, specs in REQUIRED.items():
        assert fn in router_funcs, f"missing function {fn}"
        for method, path in specs:
            assert (method, path) in router_funcs[fn], f"{fn} missing {method} {path}"

def test_public_endpoint_no_admin_dependency():
    fn = "jitsi_config_get"
    func_node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
    for d in func_node.args.defaults:
        if isinstance(d, ast.Call) and (getattr(d.func, "attr", "") == "Depends" or getattr(d.func, "id", "") == "Depends"):
            for a in d.args:
                if getattr(a, "id", "") == "get_current_admin":
                    raise AssertionError("jitsi_config_get must be public (no admin dependency)")

def test_admin_endpoint_has_admin_dependency():
    fn = "jitsi_config_set"
    func_node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn)
    has_admin = False
    for d in func_node.args.defaults:
        if isinstance(d, ast.Call) and (getattr(d.func, "attr", "") == "Depends" or getattr(d.func, "id", "") == "Depends"):
            for a in d.args:
                if getattr(a, "id", "") == "get_current_admin":
                    has_admin = True
    assert has_admin, "jitsi_config_set must require admin dependency"

def test_jitsi_config_model_exists():
    model_found = any(isinstance(n, ast.ClassDef) and n.name == "JitsiConfigIn" for n in ast.walk(TREE))
    assert model_found, "JitsiConfigIn model not found"

def test_defaults_defined():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if getattr(target, "id", "") == "JITSI_DEFAULTS":
                    assert isinstance(node.value, ast.Dict)
                    keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                    assert "enabled" in keys
                    assert "domain" in keys
                    assert "default_room_prefix" in keys
                    assert "jwt_secret" in keys
                    return
    raise AssertionError("JITSI_DEFAULTS not found")

def test_router_registered_in_init():
    """jitsi must be imported in the `from . import (...)` tuple AND its router included."""
    INIT = pathlib.Path(__file__).resolve().parents[1] / "portal" / "routes" / "__init__.py"
    tree = ast.parse(INIT.read_text())

    imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is None:
            for alias in node.names:
                if alias.name == "jitsi":
                    imported = True
    assert imported, "jitsi not imported in routes/__init__.py"

    included = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if getattr(f, "attr", "") == "include_router" and node.args:
                a = node.args[0]
                if getattr(a, "attr", "") == "router" and getattr(a.value, "id", "") == "jitsi":
                    included = True
    assert included, "jitsi.router not included in routes/__init__.py"


# ---------------------------------------------------------------------------
# Regression tests — behaviour, not AST.
#
# The AST-only suite above checked endpoint names, dependency wiring and the
# presence of JITSI_DEFAULTS keys, and therefore happily passed while the
# PUBLIC endpoint returned the whole stored dict including `jwt_secret`
# (CRITICAL secret leak). These tests execute the real projection and the real
# handler so that removing the whitelist makes them FAIL.
# ---------------------------------------------------------------------------
import importlib
import pytest as _pytest

jitsi_mod = importlib.import_module("portal.routes.jitsi")


def test_public_projection_never_contains_jwt_secret():
    out = jitsi_mod._public_jitsi({
        "enabled": True,
        "domain": "meet.example.com",
        "default_room_prefix": "intercloud",
        "jwt_secret": "SUPERSECRET",
    })
    assert "jwt_secret" not in out, "public projection leaked jwt_secret"
    assert "SUPERSECRET" not in repr(out), "secret value leaked in payload"
    assert out["jwt_secret_set"] is True
    assert set(out) == {"enabled", "domain", "default_room_prefix", "jwt_secret_set"}


def test_public_projection_drops_unknown_keys():
    """Legacy/unknown keys in the stored doc must not pass through either."""
    out = jitsi_mod._public_jitsi({
        "enabled": False, "domain": "d", "default_room_prefix": "p",
        "jwt_secret": "", "unexpected_key": "x",
    })
    assert "jwt_secret" not in out
    assert "unexpected_key" not in out
    assert out["jwt_secret_set"] is False


def test_public_projection_handles_none_and_empty():
    for cfg in (None, {}):
        out = jitsi_mod._public_jitsi(cfg)
        assert "jwt_secret" not in out
        assert out["jwt_secret_set"] is False
        assert out["domain"] == jitsi_mod.JITSI_DEFAULTS["domain"]


def test_config_model_field_is_default_room_prefix_not_room_prefix():
    """AdminJitsi used to POST `room_prefix`, which Pydantic v2 silently
    dropped — so every save reset the prefix to the model default."""
    fields = set(jitsi_mod.JitsiConfigIn.model_fields)
    assert "default_room_prefix" in fields
    assert "room_prefix" not in fields


class _FakeSettings:
    def __init__(self, doc=None):
        self.doc = doc

    async def find_one(self, q):
        if self.doc and self.doc.get("key") == q.get("key"):
            return self.doc
        return None

    async def update_one(self, q, update, upsert=False):
        self.doc = {"key": q["key"], "value": update["$set"]["value"]}


class _FakeDb:
    def __init__(self, doc=None):
        self.settings = _FakeSettings(doc)


def _patch_db(monkeypatch, doc=None):
    db = _FakeDb(doc)

    async def _fake_get_db():
        return db

    monkeypatch.setattr(jitsi_mod, "_get_db", _fake_get_db)
    return db


async def test_public_get_never_returns_jwt_secret(monkeypatch):
    _patch_db(monkeypatch, {"key": "jitsi_config", "value": {
        "enabled": True, "domain": "meet.example.com",
        "default_room_prefix": "intercloud", "jwt_secret": "LEAKME"}})
    res = await jitsi_mod.jitsi_config_get()
    assert "jwt_secret" not in res
    assert "LEAKME" not in repr(res)
    assert res["jwt_secret_set"] is True
    assert res["default_room_prefix"] == "intercloud"


async def test_public_get_on_empty_settings_uses_defaults(monkeypatch):
    _patch_db(monkeypatch, None)
    res = await jitsi_mod.jitsi_config_get()
    assert "jwt_secret" not in res
    assert res["enabled"] is False
    assert res["jwt_secret_set"] is False


async def test_admin_save_with_empty_secret_preserves_stored_secret(monkeypatch):
    """Empty field = KEEP the existing secret (as the admin UI promises)."""
    db = _patch_db(monkeypatch, {"key": "jitsi_config", "value": {
        "enabled": True, "domain": "old.example.com",
        "default_room_prefix": "oldprefix", "jwt_secret": "KEEPME"}})
    payload = jitsi_mod.JitsiConfigIn(
        enabled=True, domain="new.example.com",
        default_room_prefix="newprefix", jwt_secret="")
    res = await jitsi_mod.jitsi_config_set(payload, admin={"role": "admin"})

    stored = db.settings.doc["value"]
    assert stored["jwt_secret"] == "KEEPME", "secret was wiped by an empty save"
    assert stored["default_room_prefix"] == "newprefix", "prefix silently reset"
    assert stored["domain"] == "new.example.com"
    assert "jwt_secret" not in res
    assert res["jwt_secret_set"] is True


async def test_admin_save_with_new_secret_replaces_it(monkeypatch):
    db = _patch_db(monkeypatch, {"key": "jitsi_config", "value": {
        "enabled": True, "domain": "d", "default_room_prefix": "p",
        "jwt_secret": "OLD"}})
    payload = jitsi_mod.JitsiConfigIn(
        enabled=True, domain="d", default_room_prefix="p", jwt_secret="NEW")
    res = await jitsi_mod.jitsi_config_set(payload, admin={"role": "admin"})

    assert db.settings.doc["value"]["jwt_secret"] == "NEW"
    assert "NEW" not in repr(res)
    assert res["jwt_secret_set"] is True


# ---------------------------------------------------------------------------
# Defect-fix regression (round 3): input validation + corrupt-document resilience
# ---------------------------------------------------------------------------
def test_blank_domain_is_rejected():
    with _pytest.raises(Exception):
        jitsi_mod.JitsiConfigIn(enabled=True, domain="", default_room_prefix="p", jwt_secret="")


def test_blank_room_prefix_is_rejected():
    with _pytest.raises(Exception):
        jitsi_mod.JitsiConfigIn(enabled=True, domain="d", default_room_prefix="   ", jwt_secret="")


def test_whitespace_is_stripped_from_domain_and_prefix():
    m = jitsi_mod.JitsiConfigIn(
        enabled=True, domain="  d.example.com ", default_room_prefix="  ic  ", jwt_secret="")
    assert m.domain == "d.example.com"
    assert m.default_room_prefix == "ic"


def test_public_projection_survives_corrupt_non_dict_document():
    """Dokumen settings korup TIDAK boleh menjatuhkan endpoint PUBLIK."""
    for bad in ("oops", ["a"], 42, 3.5, True):
        out = jitsi_mod._public_jitsi(bad)
        assert "jwt_secret" not in out
        assert out["domain"] == jitsi_mod.JITSI_DEFAULTS["domain"]
        assert out["default_room_prefix"] == jitsi_mod.JITSI_DEFAULTS["default_room_prefix"]
        assert out["jwt_secret_set"] is False


def test_public_projection_none_values_fall_back_to_defaults():
    out = jitsi_mod._public_jitsi({"domain": None, "default_room_prefix": "", "enabled": None})
    assert out["domain"] == jitsi_mod.JITSI_DEFAULTS["domain"]
    assert out["default_room_prefix"] == jitsi_mod.JITSI_DEFAULTS["default_room_prefix"]
    assert out["enabled"] is False


def test_whitespace_only_secret_reports_not_set():
    """Konsisten dgn setter yg menganggap '   ' kosong."""
    out = jitsi_mod._public_jitsi({"jwt_secret": "   "})
    assert out["jwt_secret_set"] is False


async def test_whitespace_only_secret_preserves_stored_secret(monkeypatch):
    db = _patch_db(monkeypatch, {"key": "jitsi_config", "value": {
        "enabled": True, "domain": "d", "default_room_prefix": "p", "jwt_secret": "KEEPME"}})
    payload = jitsi_mod.JitsiConfigIn(
        enabled=True, domain="d", default_room_prefix="p", jwt_secret="   ")
    await jitsi_mod.jitsi_config_set(payload, admin={"role": "admin"})
    assert db.settings.doc["value"]["jwt_secret"] == "KEEPME"


async def test_setter_survives_corrupt_stored_document(monkeypatch):
    db = _patch_db(monkeypatch, {"key": "jitsi_config", "value": "corrupt"})
    payload = jitsi_mod.JitsiConfigIn(
        enabled=True, domain="d", default_room_prefix="p", jwt_secret="")
    res = await jitsi_mod.jitsi_config_set(payload, admin={"role": "admin"})
    assert "jwt_secret" not in res
    assert res["jwt_secret_set"] is False
    assert db.settings.doc["value"]["domain"] == "d"
