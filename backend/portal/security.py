"""Phase-2 security hardening — shared limiter + headers + log filter.

- `limiter` is a slowapi Limiter, imported from routes.py to decorate the
  4 auth endpoints (login/register/forgot/reset). One IP → N req/min.
- `SecurityHeadersMiddleware` adds HSTS, X-Content-Type-Options,
  X-Frame-Options, Referrer-Policy, Permissions-Policy, and a CSP in
  `Content-Security-Policy-Report-Only` mode (user chose report-only).
- `SensitiveLogFilter` masks accidental password/token/JWT/email leaks
  in log lines.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ============================================================
# Rate limiter — one instance shared across the app
# ============================================================
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],   # no global cap; opt-in via decorators only
    headers_enabled=False,   # BaseHTTPMiddleware-wrapped responses break the injector; keep off
    storage_uri="memory://",
)

# Fixed policies (documented at each auth endpoint):
AUTH_LOGIN_LIMIT           = "10/minute"   # login attempts
AUTH_REGISTER_LIMIT        = "5/hour"      # registration
AUTH_FORGOT_LIMIT          = "5/hour"      # forgot-password (avoid enumeration/spam)
AUTH_RESET_LIMIT           = "10/hour"     # reset submissions


# ============================================================
# Security headers (report-only CSP as requested)
# ============================================================
CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "script-src  'self' 'unsafe-inline' https://www.google.com https://www.gstatic.com "
    "            https://www.googletagmanager.com https://images.pexels.com; "
    "style-src   'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src    'self' https://fonts.gstatic.com data:; "
    "img-src     'self' https: data: blob:; "
    "connect-src 'self' https: wss:; "
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
        # Report-only per user preference — never blocks, only reports.
        h.setdefault("Content-Security-Policy-Report-Only", CSP_REPORT_ONLY)
        # Kill legacy XSS heuristics in old browsers; modern browsers ignore.
        h.setdefault("X-XSS-Protection", "0")
        return response


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
