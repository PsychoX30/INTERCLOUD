"""Phase-2 security hardening - shared limiter + headers + log filter.

- `limiter` is a slowapi Limiter, imported from routes.py to decorate the
  4 auth endpoints (login/register/forgot/reset). One IP → N req/min.
- `SecurityHeadersMiddleware` adds HSTS, X-Content-Type-Options,
  X-Frame-Options, Referrer-Policy, Permissions-Policy, and an ENFORCED
  `Content-Security-Policy` (report-only kept alongside for one release
  cycle as a safety net).
- `SensitiveLogFilter` masks accidental password/token/JWT/email leaks
  in log lines.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address

# Peer addresses whose X-Forwarded-For header we believe. nginx terminates TLS
# and proxies to 127.0.0.1:8001, so loopback is the only legitimate source.
#
# This set alone is NOT a security boundary: a local process connecting to
# 127.0.0.1:8001 is also a loopback peer, and it writes the header itself. The
# transport lock is what makes the check meaningful - an iptables owner match
# (service `intercloud-lock-backend`) drops every uid except nginx's on that
# port, so any request that reaches this function with a loopback peer really
# did come through nginx, which overwrites the header with `$remote_addr`.
# Keep the two together: removing the iptables rule re-opens audit-IP forgery.
_TRUSTED_PROXY_PEERS = {"127.0.0.1", "::1", "localhost"}


def _client_ip(request):
    """Rate-limit key: prefer the LAST X-Forwarded-For hop, falling back to the
    socket peer address. Without this, every production user behind the reverse
    proxy shares one 127.0.0.1 bucket and legitimate users rate-limit each other
    out.

    This value is not just a limiter key: `_log_login_attempt` stores it as the
    audit IP and `_maybe_auto_block` bans it. A forgeable value therefore lets a
    local process ban an arbitrary public address - measured before the ingress
    lock existed, 8 failing logins sent straight at :8001 with
    `X-Forwarded-For: 198.51.100.9` produced a blocked_ips row for
    198.51.100.9 (`reason=auto_block_threshold`).

    Two changes closed it, and both are load-bearing:

    1. uvicorn runs with `--forwarded-allow-ips=__no_trusted_proxy__`, so its
       ProxyHeadersMiddleware leaves `scope["client"]` alone and the peer below
       is the true socket peer. With the default (`127.0.0.1`) the middleware
       overwrote `scope["client"]` with the header, so this function compared a
       forged peer against a forged peer and always "passed".
    2. nginx's /api/ block overwrites `X-Forwarded-For` with `$remote_addr`
       instead of appending, so the last hop is the address nginx saw.

    Note the peer check alone cannot separate nginx from a local process - both
    are loopback. The iptables owner match on :8001 is what makes it sound.
    """
    peer = get_remote_address(request)
    if peer in _TRUSTED_PROXY_PEERS:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            ip = xff.split(",")[-1].strip()
            if ip:
                return ip
    return peer


from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ============================================================
# Rate limiter - one instance shared across the app
# ============================================================
def _limiter_storage_uri() -> str:
    """MongoDB-backed counters, falling back to memory.

    `memory://` is per-process. uvicorn runs `--workers 2`, so every policy
    below was really 2x its stated rate, split by whichever worker the kernel
    picked: `AUTH_REGISTER_LIMIT = 5/hour` allowed up to 10, `AUTH_LOGIN_LIMIT
    = 10/minute` up to 20, and the effective rate doubled again on every
    restart. (Measured: a 12-request burst against /auth/login produced one
    429 from only one of the two workers.)

    MongoDB is already a hard dependency of this app, so the counters cost no
    new infrastructure and are shared by both workers.

    Order matters: `server.py` imports this module at line 14 but calls
    `load_dotenv()` at line 19, so `MONGO_URL` is still unset when this runs.
    We therefore load `backend/.env` ourselves (override=False, so the app's
    own later call is unaffected). Getting this wrong silently degrades to
    the per-process limiter, which is the bug this function exists to fix.

    Any failure - missing env, missing pymongo, bad URI - falls back to
    memory. A limiter outage must never take the API down; a lenient limiter
    is strictly better than an unavailable one.
    """
    uri = os.environ.get("MONGO_URL")
    if not uri:
        try:
            from dotenv import load_dotenv
            from pathlib import Path
            # portal/security.py -> portal -> backend
            env_path = Path(__file__).resolve().parents[1] / ".env"
            load_dotenv(env_path, override=False)
            uri = os.environ.get("MONGO_URL")
        except Exception:
            uri = None
    if not uri:
        return "memory://"
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        return "memory://"
    try:
        from limits.storage import MongoDBStorage
    except Exception:  # pragma: no cover - dependency missing
        return "memory://"
    # Touch the connection once, here, with short timeouts. Doing it at import
    # rather than on the first login means a wrong URI or missing grant
    # degrades to the in-memory limiter at startup instead of failing every
    # rate-limited request later.
    try:
        MongoDBStorage(
            uri,
            database_name=os.environ.get("DB_NAME") or "intercloud_portal",
            serverSelectionTimeoutMS=1500,
            connectTimeoutMS=1500,
            socketTimeoutMS=2000,
        ).storage  # property -> __initialize_database (creates its indexes)
    except Exception as e:  # pragma: no cover - environment specific
        logging.getLogger("portal.security").warning(
            "[ratelimit] mongo storage unavailable (%s: %s) - falling back to "
            "per-process memory limiter; limits will be per worker until fixed",
            type(e).__name__, str(e)[:160],
        )
        return "memory://"
    return uri


def _limiter_db_name() -> str:
    """Database the limiter counters live in - the app's own DB.

    The app's mongo credentials are granted on DB_NAME only, so this has to
    match it. `server.py` also calls `load_dotenv()`, but this module is
    imported before that line runs, hence the local load below.
    """
    name = os.environ.get("DB_NAME")
    if not name:
        try:
            from dotenv import load_dotenv
            from pathlib import Path
            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
            name = os.environ.get("DB_NAME")
        except Exception:
            name = None
    return name or "intercloud_portal"


limiter = Limiter(
    key_func=_client_ip,
    default_limits=[],   # no global cap; opt-in via decorators only
    headers_enabled=False,   # BaseHTTPMiddleware-wrapped responses break the injector; keep off
    storage_uri=_limiter_storage_uri(),
    # Keep the limiter's own bookkeeping out of the app database; a separate
    # db name keeps the counters from polluting `db.users` etc.
    storage_options={
        # MUST be the app's own database. The mongo user granted to this app is
        # scoped to DB_NAME only: pointing the limiter at any other database
        # fails with `not authorized on <db> to execute command` at the first
        # rate-limited request (measured with "intercloud_ratelimit"). The
        # counters live in their own collections (`counters`, `windows`) and
        # never touch business data.
        "database_name": _limiter_db_name(),
        # Bounded: pymongo's default server-selection timeout is 30s, which
        # would turn a mongo hiccup into a 30s hang on every rate-limited
        # request. The counters are best-effort; fail fast instead.
        "serverSelectionTimeoutMS": 1500,
        "connectTimeoutMS": 1500,
        "socketTimeoutMS": 2000,
    },
)


def _install_safe_mongo_storage_del() -> None:
    """Replace limits' `MongoDBStorageBase.__del__` with a shutdown-safe one.

    The stock destructor is:

        def __del__(self):
            if self.storage:
                self.storage.close()

    Two problems, both measured on this host:
      1. `self.storage` is a property that LAZILY CREATES the pymongo client.
         Touching it during teardown therefore opens a new connection at the
         worst possible moment (and, with mongo unreachable, raised
         ServerSelectionTimeoutError out of `__del__`).
      2. `pymongo.MongoClient.close()` imports modules while the interpreter is
         shutting down and raises `ImportError: sys.meta_path is None`.

    Neither can be caught by the caller - exceptions in `__del__` are printed
    as "Exception ignored in" and nothing else - so every worker restart wrote
    two tracebacks into the backend error log and made a clean restart look
    like a crash. That noise is how a real failure gets missed later.

    This only replaces the cleanup path; behaviour during normal operation is
    untouched. Idempotent and fully guarded.
    """
    try:
        from limits.storage.mongodb import MongoDBStorageBase

        def _safe_del(self) -> None:
            try:
                client = getattr(self, "_storage", None)
                if client is not None:
                    client.close()
            except Exception:
                # Shutdown, or the client was already torn down. Nothing to do
                # and nowhere useful to report it.
                pass

        MongoDBStorageBase.__del__ = _safe_del
    except Exception:  # pragma: no cover - dependency layout changed
        logging.getLogger("portal.security").warning(
            "[ratelimit] could not install shutdown-safe mongo destructor; "
            "expect 'Exception ignored in MongoDBStorageBase.__del__' on restart"
        )


_install_safe_mongo_storage_del()


def _warm_limiter_storage(lim) -> None:
    """Force the limiter's storage to initialise now instead of on teardown.

    `limits` MongoDBStorage initialises its collection lazily, and its
    `__del__` re-triggers that initialisation at interpreter shutdown - when
    pymongo is already being torn down. Measured: every worker restart wrote a
    ServerSelectionTimeoutError traceback from `MongoDBStorageBase.__del__`
    into the backend error log, which makes a clean restart look like a crash.

    Touching `.storage` once satisfies the property's guard, so teardown does
    no I/O. Failure is non-fatal: slowapi swallows storage errors per request
    and the app fails open, which is the right trade for a rate limiter.
    """
    try:
        storage = getattr(lim, "_storage", None)
        inner = getattr(storage, "storage", None)
        if inner is not None:
            _ = inner
    except Exception as e:  # pragma: no cover - environment specific
        logging.getLogger("portal.security").warning(
            "[ratelimit] storage warm-up failed (%s) - counters may be skipped",
            type(e).__name__,
        )


_warm_limiter_storage(limiter)

# Fixed policies (documented at each auth endpoint):
AUTH_LOGIN_LIMIT           = "10/minute"   # login attempts
AUTH_REGISTER_LIMIT        = "5/hour"      # registration
AUTH_FORGOT_LIMIT          = "5/hour"      # forgot-password (avoid enumeration/spam)
AUTH_RESET_LIMIT           = "10/hour"     # reset submissions
PUBLIC_STATUS_LIMIT        = "60/minute"   # unauthenticated /public/status + sitemap


# ============================================================
# Security headers - CSP is ENFORCED (report-only kept alongside
# for one release cycle as a safety net; same policy string).
# ============================================================
CSP_POLICY = (
    "default-src 'self'; "
    "script-src  'self' 'unsafe-eval' https://www.google.com https://www.gstatic.com "
    "            https://www.googletagmanager.com https://images.pexels.com; "
    "script-src-attr 'none'; "
    "style-src   'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src    'self' https://fonts.gstatic.com data:; "
    "img-src     'self' https: data: blob:; "
    "connect-src 'self' wss://intercloud-digital.com; "
    "frame-src   'self' https://www.google.com; "
    "object-src  'none'; "
    "base-uri    'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "report-uri  /api/csp-report"
)

PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
    "accelerometer=(), autoplay=(self), fullscreen=(self)"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach a curated set of security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        h = response.headers
        # Strict transport (browser only honours when served over HTTPS)
        h.setdefault("Strict-Transport-Security",
                     "max-age=31536000; includeSubDomains; preload")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        # ENFORCED CSP - violations are blocked by the browser.
        h.setdefault("Content-Security-Policy", CSP_POLICY)
        # Report-only kept for one release cycle (safety net + telemetry).
        h.setdefault("Content-Security-Policy-Report-Only", CSP_POLICY)
        # Kill legacy XSS heuristics in old browsers; modern browsers ignore.
        h.setdefault("X-XSS-Protection", "0")
        return response


# ============================================================
# HTML escaping for outbound email
# ============================================================
def escape_html(value) -> str:
    """Escape a value for interpolation into an HTML email body.

    User-controlled text (display name, company, ticket subject) is stored
    verbatim by design - the React portal renders it as text and React escapes
    it. Email is different: those strings are concatenated into HTML strings,
    so an unescaped name is real stored HTML injection into every message the
    system sends to that address.

    Use on EVERY dynamic value inside an f-string HTML body. Not needed for
    server-generated values (URLs you built yourself), but harmless there.
    """
    if value is None:
        return ""
    return (str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;"))


# ============================================================
# Sensitive log filter
# ============================================================
_JWT_RX      = re.compile(r"eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}")
_BEARER_RX   = re.compile(r"(?i)Bearer\s+[A-Za-z0-9_\-\.]+")
_PWD_RX      = re.compile(r"(?i)(password|passwd|pwd)['\"\s:=]+[^\s,'\"]+")
_TOKEN_RX    = re.compile(r"(?i)(token|api[_\-]?key|secret)['\"\s:=]+[A-Za-z0-9_\-]{6,}")
_EMAIL_RX    = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _mask_email(match: re.Match) -> str:
    local, domain = match.group(1), match.group(2)
    if len(local) <= 2:
        masked = "*" * len(local)
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


class SensitiveLogFilter(logging.Filter):
    """Best-effort masking of JWTs, bearer tokens, passwords, API keys, and
    email addresses in log records. Not a substitute for structured logging
    but stops accidental leaks from string-formatted debug lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        original = msg
        msg = _JWT_RX.sub("<jwt:redacted>", msg)
        msg = _BEARER_RX.sub("Bearer <redacted>", msg)
        msg = _PWD_RX.sub(r"\1=<redacted>", msg)
        msg = _TOKEN_RX.sub(r"\1=<redacted>", msg)
        msg = _EMAIL_RX.sub(_mask_email, msg)
        if msg != original:
            # Overwrite the pre-formatted message; args are consumed by getMessage
            record.msg = msg
            record.args = ()
        return True


def install_log_filter() -> None:
    """Attach the SensitiveLogFilter to the root logger + uvicorn/portal loggers."""
    flt = SensitiveLogFilter()
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error",
                 "portal", "portal.password_reset", "portal.emails"):
        logging.getLogger(name).addFilter(flt)


# ============================================================
# CSP report handler payload (used by server.py route)
# ============================================================
async def log_csp_report(body: bytes) -> None:
    """Log a Content-Security-Policy violation report at WARN level."""
    import json
    try:
        data = json.loads(body or b"{}")
    except Exception:
        data = {"raw": (body or b"")[:400].decode(errors="replace")}
    logging.getLogger("portal.csp").warning(f"[csp-violation] {data}")


# ============================================================
# Threat scoring — pure, deterministic, testable anomaly detector
# ============================================================
def compute_threat_score(*, failures: int, distinct_ips: int,
                         distinct_emails: int, threshold: int) -> dict:
    """Score an IP's failed-login pattern on 0..100 and map to a level.

    Three independent signals, each clamped to 0..1, combined so that volume
    (the strongest and most objective signal) can reach 100 on its own while
    the other two only add on top:

      - volume:        failure count vs the configured auto-block threshold.
      - enumeration:   password spraying — many accounts from one source IP.
      - distribution:  distributed brute force — one account from many IPs.

    Reaching the block threshold is therefore decisive by itself: volume
    saturates at 1.0 there, so the score hits 100 without needing a special
    case. The total is capped at 100 so no combination leaves the range.

    level: score >= 70 → "high", >= 40 → "medium", else "low".

    Pure function: no DB, no network, no clock. Safe to unit-test and to run
    anywhere in the login path.
    """
    def _clamp(x: float) -> float:
        return max(0.0, min(1.0, x))

    # Volume saturates at the block threshold (see docstring).
    volume = _clamp(float(failures) / float(threshold)) if threshold > 0 else 0.0
    # Password spraying: one source IP touching many distinct accounts.
    # Saturates at 6 distinct accounts — diminishing returns beyond that.
    enumeration = _clamp((distinct_emails - 1) / 5.0) if distinct_emails > 1 else 0.0
    # Distributed brute force: one account probed from many source IPs.
    distribution = _clamp((distinct_ips - 1) / 5.0) if distinct_ips > 1 else 0.0

    raw = 100.0 * (volume + 0.3 * enumeration + 0.15 * distribution)
    score = int(min(100, round(raw)))
    level = "high" if score >= 70 else "medium" if score >= 40 else "low"
    return {
        "score": score,
        "level": level,
        "volume": round(volume, 3),
        "enumeration": round(enumeration, 3),
        "distribution": round(distribution, 3),
    }
