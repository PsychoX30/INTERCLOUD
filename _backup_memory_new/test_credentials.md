# Test Credentials

## Admin Account
- Email: `admin@intercloud.io`
- Password: `admin123`
- Role: `admin`

## Auth Endpoints
- POST /api/auth/register
- POST /api/auth/login
- POST /api/auth/logout
- GET  /api/auth/me
- POST /api/auth/forgot-password
- POST /api/auth/reset-password

## Notes
- Admin is auto-seeded from backend/.env on startup.
- Login accepts email + password; tokens stored via httpOnly cookies AND returned in JSON for localStorage fallback.
- CAPTCHA (Cloudflare Turnstile) is disabled by default (TURNSTILE_ENABLED=false). Set to true after providing keys.
