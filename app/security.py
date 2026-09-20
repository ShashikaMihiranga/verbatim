"""Response security headers for every route."""
import os
import re

from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

# The chart pages use inline SVG/CSS and the Jost font from Google Fonts, so those are allowed.
CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "script-src 'self'; "
    "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
)

CLERK_IMG = "https://img.clerk.com"
CLERK_BOT = "https://challenges.cloudflare.com"  # Clerk bot protection (Cloudflare Turnstile)
_HOST = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clerk_host() -> str | None:
    """CLERK_FRONTEND_API as a bare host, or None when unset or not a plain host name.

    Anything else is ignored so an odd value can never inject directives into the header.
    """
    raw = os.environ.get("CLERK_FRONTEND_API")
    if raw is None:
        raw = get_settings().clerk_frontend_api or ""
    host = raw.strip().lower().removeprefix("https://").rstrip("/")
    return host if _HOST.match(host) else None


def build_csp(frontend_api: str | None) -> str:
    """The strict base policy, plus what Clerk needs when CLERK_FRONTEND_API is set."""
    if not frontend_api:
        return CSP
    fapi = f"https://{frontend_api}"
    return (
        "default-src 'self'; "
        f"img-src 'self' data: {fapi} {CLERK_IMG}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        f"script-src 'self' {fapi} {CLERK_BOT}; "
        f"connect-src 'self' {fapi} {CLERK_BOT}; "
        f"frame-src {fapi} {CLERK_BOT}; "
        "worker-src 'self' blob:; "  # Clerk's script uses a blob worker
        "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
    )


HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for k, v in HEADERS.items():
            response.headers.setdefault(k, v)
        response.headers["Content-Security-Policy"] = build_csp(clerk_host())
        return response
