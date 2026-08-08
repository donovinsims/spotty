"""Optional single-user auth for the web UI (Phase 3).

When ``PT_AUTH_TOKEN`` is set (via config, i.e. ``cfg.auth_token``), every
route except /healthz, /static/*, /sw.js, /manifest.webmanifest and the auth
routes themselves (/login, /logout) requires a valid token, accepted in two
forms:

  * ``Authorization: Bearer <token>`` header  (scripts / API calls)
  * ``pt_token`` cookie                       (set by the /login page)

(Query-string ``?token=`` is deliberately NOT accepted: uvicorn access logs
write the full request target, so a query token would leak the credential to
logs/serve.out.log.)

Token comparison is constant-time (``hmac.compare_digest``).  An empty /
unset token disables auth entirely, preserving the Phase 1/2 single-user LAN
behaviour.

Unauthenticated requests are handled per client type:
  * plain browser GET      -> 302 redirect to /login?next=<path>
  * HTMX request           -> 401 JSON + ``HX-Redirect: /login`` (full nav)
  * everything else (API)  -> 401 JSON
"""

from __future__ import annotations

import hmac
from typing import Optional
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

#: Paths that never require a token.
PUBLIC_PATHS = (
    "/healthz",
    "/login",
    "/logout",
    # PWA shell assets -- they leak nothing, and the service worker must be
    # installable before the login page can be reached offline.
    "/sw.js",
    "/manifest.webmanifest",
)


def token_matches(provided: Optional[str], expected: Optional[str]) -> bool:
    """Constant-time token comparison. False when either side is empty."""
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def token_from_request(request: Request) -> Optional[str]:
    """Extract a token from the request (Bearer header or pt_token cookie)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        return token or None
    cookie = request.cookies.get("pt_token")
    return cookie or None


def is_authorized(request: Request, expected: str) -> bool:
    """True when the request carries a token equal to ``expected``."""
    return token_matches(token_from_request(request), expected)


def is_public_path(path: str) -> bool:
    return path == "/healthz" or path.startswith("/static") or path in PUBLIC_PATHS


def unauthorized_response(request: Request) -> JSONResponse | RedirectResponse:
    """Redirect browser GETs to /login; 401 JSON for API/HTMX requests."""
    is_hx = request.headers.get("hx-request") is not None
    if is_hx:
        # htmx follows HX-Redirect with a full page navigation to the login.
        response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
        response.headers["HX-Redirect"] = "/login"
        return response
    is_browser = "text/html" in request.headers.get("accept", "")
    if request.method == "GET" and is_browser:
        # path only -- never echo the query string into next= (it can carry a
        # ?token= secret, which would leak into logs and Referer headers).
        next_url = request.url.path
        return RedirectResponse(
            url=f"/login?next={quote(next_url, safe='')}", status_code=302
        )
    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
