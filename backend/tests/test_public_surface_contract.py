"""Contract for the *unauthenticated* surface of the API.

Every route that answers without a credential is an attack surface, and the
danger is not the one that is there today — it is the one that gets added next
month because nothing was watching. This test is the watcher.

What it asserts:

1. The set of routes that resolve to no auth guard is **exactly** the documented
   allowlist below. A new unauthenticated route fails the build; a stale
   allowlist entry (route deleted or now guarded) also fails, so the list cannot
   rot into a rubber stamp.
2. Every unauthenticated route carries a written reason, and state-changing ones
   are separately enumerated — a public GET of marketing content and a public
   POST that writes to the database are not the same risk, and the allowlist
   should not be allowed to blur them.
3. `/api/status` stays gone, and nothing touches the `status_checks` collection.
   That pair was leftover scaffold: unauthenticated POST wrote a document and
   unauthenticated GET read the collection back, which is free storage for
   anyone on the internet and an enumeration primitive on top.

Auth resolution notes (both were bugs in the first draft of this audit):

* `Depends(get_current_admin)` is a Call whose *func* is `Depends`; the guard is
  in `args[0]`. Matching only call names reported every gated route as naked.
* `Depends(_get_current_owner)` is a local wrapper that checks the role itself.
  A module-level function whose defaults carry a guard counts as a carrier, or
  the wrapper looks like no auth at all.

AST only: no app import, no DB, no network.
"""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROUTES_DIR = BACKEND / "portal" / "routes"

GUARDS = {
    "get_current_user", "get_current_admin", "get_current_staff",
    "get_current_content", "get_current_kb_author", "require_roles",
}
# Authenticating inside the handler body instead of via a dependency.
# `client_vm_console_ws` is the only such case: browsers cannot set headers on
# a WebSocket upgrade, so the JWT arrives as ?token= and is decoded in-handler.
IN_BODY_AUTH = {"decode_token", "_resolve_user"}

VERBS = {"get", "post", "put", "patch", "delete", "head", "options", "websocket"}

# ---------------------------------------------------------------------------
# The allowlist. Key: (file, METHOD, path-without-router-prefix). Value: why.
# Adding an entry is a deliberate act — write the reason.
# ---------------------------------------------------------------------------
PUBLIC_ROUTES = {
    # ---- auth: the way in. Rate-limited; guarded by _is_ip_blocked. ----
    ("auth.py", "GET", "/auth/config"): "login page needs to know 2FA/branding flags before a token exists",
    ("auth.py", "POST", "/auth/login"): "credential exchange, the login itself",
    ("auth.py", "POST", "/auth/login/2fa"): "second factor step of the login",
    ("auth.py", "POST", "/auth/register"): "self-service signup",
    ("auth.py", "POST", "/auth/forgot-password"): "reset request by email; rate-limited to blunt enumeration",
    ("auth.py", "POST", "/auth/reset-password"): "completes the reset with a mailed token",

    # ---- payment provider callbacks. Verified by signature, not by JWT. ----
    ("billing.py", "POST", "/webhooks/{provider}"): "Duitku/gateway callback; signature-verified, no user session exists",

    # ---- tokenised public links: possession of the token IS the credential ----
    ("billing.py", "GET", "/portal-public/pay/{token}"): "invoice pay view for a mailed link",
    ("billing.py", "POST", "/portal-public/pay/{token}/pay-online"): "pay a mailed invoice link",
    ("business_overhaul.py", "POST", "/documents/shared/{token}/unlock"): "password check for a shared folder link",
    ("business_overhaul.py", "GET", "/documents/shared/{token}"): "shared folder listing by unguessable token",
    ("business_overhaul.py", "GET", "/documents/shared/{token}/file/{did}"): "file inside a shared folder, by token",
    ("business.py", "GET", "/media/file/{mid}"): "CMS media referenced by public articles and the landing page",

    # ---- lead capture + public forms: the marketing funnel ----
    ("catalog.py", "POST", "/portal-public/leads"): "landing-page lead form",
    ("catalog.py", "GET", "/portal-public/forms/{identifier}"): "renders a public form definition",
    ("catalog.py", "POST", "/portal-public/forms/{identifier}/submit"): "submits a public form",
    ("business.py", "GET", "/register/crm-prefill"): "prefills signup from a sales-shared link",

    # ---- public catalogue: prices and products, already on the landing page ----
    ("catalog.py", "GET", "/portal-public/categories"): "public product catalogue",
    ("catalog.py", "GET", "/portal-public/products"): "public product catalogue",
    ("catalog.py", "GET", "/portal-public/addons"): "public add-on catalogue",

    # ---- public site content / SEO / status page ----
    ("cms.py", "GET", "/branding"): "logo and colour tokens for the public site",
    ("cms.py", "GET", "/landing-content"): "landing page copy",
    ("cms.py", "GET", "/public/articles"): "published articles only",
    ("cms.py", "GET", "/public/articles/tags"): "tag index for published articles",
    ("cms.py", "GET", "/public/articles/{slug}"): "one published article",
    ("cms.py", "GET", "/public/status"): "public status page, uptime only",
    ("cms.py", "GET", "/sitemap.xml"): "search engine sitemap",
    ("cms.py", "GET", "/seo/render/articles/{slug}"): "crawler-friendly render of a published article",
    ("cve.py", "GET", "/public/cve"): "published CVE advisories, a deliberate content surface",
    ("cve.py", "GET", "/public/cve/stats"): "counts over the same published advisories",
    ("cve.py", "GET", "/public/cve/{cve_id}"): "one published advisory",
    ("cve.py", "GET", "/public/cve-sitemap.xml"): "sitemap for the advisory index",

    # ---- Jitsi: invite-keyed meeting surface ----
    ("jitsi.py", "GET", "/jitsi/config"): "public meeting config for the embedded widget",
    ("jitsi.py", "GET", "/jitsi/meetings"): "upcoming meetings for the landing page; slugs and invite keys stripped",
    ("jitsi.py", "GET", "/jitsi/join"): "exchanges an invite key for a short-lived room token",
    ("jitsi.py", "GET", "/jitsi/room-exists"): "existence probe used during join",
    ("jitsi.py", "GET", "/jitsi/room-auth"): "room credential check during join",

    # ---- infra probes ----
    ("server.py", "GET", "/"): "constant-string liveness probe; touches no state",
    ("server.py", "POST", "/api/csp-report"): "browser CSP violation sink; a report needs no user identity",
}

# Unauthenticated AND mutating state. Kept explicit so a public writer can never
# be introduced by quietly editing the list above.
PUBLIC_WRITES = {
    ("auth.py", "POST", "/auth/login"),
    ("auth.py", "POST", "/auth/login/2fa"),
    ("auth.py", "POST", "/auth/register"),
    ("auth.py", "POST", "/auth/forgot-password"),
    ("auth.py", "POST", "/auth/reset-password"),
    ("billing.py", "POST", "/webhooks/{provider}"),
    ("billing.py", "POST", "/portal-public/pay/{token}/pay-online"),
    ("business_overhaul.py", "POST", "/documents/shared/{token}/unlock"),
    ("catalog.py", "POST", "/portal-public/leads"),
    ("catalog.py", "POST", "/portal-public/forms/{identifier}/submit"),
    ("server.py", "POST", "/api/csp-report"),
}


# ---------------------------------------------------------------- AST helpers

def _mentions(node) -> set:
    """Every identifier name reachable from `node`, including nested call args.

    Recurses into Call args because `Depends(get_current_admin)` hides the guard
    in args[0] — the single mistake that made a previous audit claim 141 naked
    staff routes that were all properly gated. Falls through to a generic walk
    for container nodes (FunctionDef, Expr, …) so an in-body auth check is found
    too: stopping at Call/Name/Attribute silently saw nothing inside a function.
    """
    names = set()

    def walk(n):
        if isinstance(n, ast.Call):
            f = n.func
            fname = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if fname:
                names.add(fname)
            for a in n.args:
                walk(a)
            for kw in n.keywords:
                walk(kw.value)
            return
        if isinstance(n, ast.Name):
            names.add(n.id)
            return
        if isinstance(n, ast.Attribute):
            names.add(n.attr)
            walk(n.value)
            return
        for child in ast.iter_child_nodes(n):
            walk(child)

    walk(node)
    return names


def _all_defaults(fn):
    defaults = list(fn.args.defaults)
    defaults += [d for d in fn.args.kw_defaults if d is not None]
    return defaults


def _carriers(tree) -> set:
    """Module-level helpers that enforce auth themselves (role-check wrappers)."""
    out = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = set()
        for d in _all_defaults(node):
            names |= _mentions(d)
        if names & GUARDS:
            out.add(node.name)
    return out


def _collect(file_name: str, tree) -> list:
    """Emit (file, METHOD, path, func, authed, reason-bits) for every route."""
    carriers = _carriers(tree)
    rows = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            verb = getattr(dec.func, "attr", None)
            if verb not in VERBS or not dec.args:
                continue
            if not isinstance(dec.args[0], ast.Constant) or not isinstance(dec.args[0].value, str):
                continue

            deps = set()
            for kw in dec.keywords:            # APIRouter(dependencies=[...])
                if kw.arg == "dependencies":
                    deps |= _mentions(kw.value)
            for d in _all_defaults(node):
                deps |= _mentions(d)

            authed = bool(deps & GUARDS) or bool(deps & carriers)
            if not authed:
                # In-handler auth (WebSocket token in the query string).
                body = _mentions(node)
                authed = bool(body & IN_BODY_AUTH) or bool(body & carriers)

            rows.append({
                "file": file_name,
                "method": verb.upper(),
                "path": dec.args[0].value,
                "func": node.name,
                "line": node.lineno,
                "authed": authed,
            })
    return rows


def _routes() -> list:
    rows = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        rows += _collect(path.name, ast.parse(path.read_text(encoding="utf-8")))
    rows += _collect("server.py", ast.parse((BACKEND / "server.py").read_text(encoding="utf-8")))
    return rows


def _public() -> dict:
    return {(r["file"], r["method"], r["path"]): r
            for r in _routes() if not r["authed"]}


# --------------------------------------------------------------------- tests

def test_route_scan_actually_finds_routes():
    """A scan that finds nothing would make every assertion below vacuous."""
    routes = _routes()
    assert len(routes) > 300, f"route scan found only {len(routes)} routes"
    assert any(r["authed"] for r in routes), "no route resolved to authed — resolver is broken"
    assert any(not r["authed"] for r in routes), "no unauthenticated route found — resolver is broken"


def test_no_undocumented_unauthenticated_route():
    """The whole point: a new public endpoint must be a deliberate, reviewed edit."""
    found = set(_public())
    unexpected = found - set(PUBLIC_ROUTES)
    assert not unexpected, (
        "unauthenticated routes that are not in the allowlist:\n"
        + "\n".join(
            f"  {f} {m:9s} {p}  (handler: "
            f"{_public()[(f, m, p)]['func']}:{_public()[(f, m, p)]['line']})"
            for f, m, p in sorted(unexpected)
        )
        + "\nAdd a guard, or add the route to PUBLIC_ROUTES with a written reason."
    )


def test_allowlist_has_no_stale_entries():
    """A dead allowlist entry is a blind spot someone will reuse."""
    found = set(_public())
    stale = set(PUBLIC_ROUTES) - found
    assert not stale, (
        "PUBLIC_ROUTES lists routes that are no longer unauthenticated (deleted "
        "or now guarded) — delete these entries:\n"
        + "\n".join(f"  {f} {m} {p}" for f, m, p in sorted(stale))
    )


def test_every_public_route_documents_a_reason():
    undocumented = [k for k, reason in PUBLIC_ROUTES.items() if len(reason.strip()) < 12]
    assert not undocumented, f"allowlist entries without a real reason: {undocumented}"


def test_public_writes_are_exactly_the_documented_set():
    """Public writes are the sharp edge: they let the internet create data.

    Any route that mutates and needs no credential has to be named here on its
    own, so growing that set takes an explicit edit rather than a copy-paste.
    """
    mutating = {
        key for key in _public()
        if key[1] in ("POST", "PUT", "PATCH", "DELETE")
    }
    added = mutating - PUBLIC_WRITES
    removed = PUBLIC_WRITES - mutating
    assert not added, (
        "unauthenticated routes that mutate state and are not in PUBLIC_WRITES: "
        f"{sorted(added)}"
    )
    assert not removed, (
        "PUBLIC_WRITES names routes that no longer mutate publicly: "
        f"{sorted(removed)}"
    )


def test_no_public_route_under_a_staff_prefix():
    """Belt and braces: staff-looking prefixes must never resolve unauthenticated.

    Prefix matching is a blunt instrument, which is exactly why it catches the
    mistake a per-route audit gets tired enough to miss.
    """
    staffy = ("/admin", "/staff", "/noc", "/finance", "/crm", "/provision",
              "/dcim", "/monitoring", "/sla", "/security", "/integrations",
              "/backup", "/outbound", "/settings")
    offenders = [(f, m, p) for (f, m, p) in _public() if p.startswith(staffy)]
    assert not offenders, f"unauthenticated routes under staff prefixes: {offenders}"


# ------------------------------------------------------- status endpoint removal

def test_dead_status_endpoints_are_gone():
    """`/status` was unauthenticated in both directions and served no caller.

    POST wrote a document and GET listed the whole collection back, so it was
    free storage plus an enumeration/DoS primitive for anyone on the internet.
    It is removed, not merely guarded — guarding dead code keeps the code.
    """
    server = ast.parse((BACKEND / "server.py").read_text(encoding="utf-8"))
    handlers = {n.name for n in server.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "create_status_check" not in handlers
    assert "get_status_checks" not in handlers

    api_paths = {
        dec.args[0].value
        for node in ast.walk(server)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for dec in node.decorator_list
        if isinstance(dec, ast.Call)
        and dec.args
        and isinstance(dec.args[0], ast.Constant)
        and isinstance(dec.args[0].value, str)
    }
    assert "/status" not in api_paths, "the /status route was reintroduced"


def test_nothing_touches_the_status_checks_collection():
    """Checked at AST level, so comments mentioning the removal do not count."""
    offenders = []
    for path in [BACKEND / "server.py"] + sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # db.status_checks / db["status_checks"]
            if (isinstance(node, ast.Attribute)
                    and node.attr == "status_checks"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "db"):
                offenders.append(f"{path.name}:{node.lineno}")
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == "status_checks"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"status_checks collection still referenced: {offenders}"
