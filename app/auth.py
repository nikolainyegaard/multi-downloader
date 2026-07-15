"""Session auth for the admin panel: username/password plus optional OIDC.

The OIDC flow (authlib, discovery URL, PKCE S256) is ported from
social-downloader and adapted to Starlette. Routes, env vars and login page
layout are unified with nyshare's admin auth:

  GET  /admin/login          login page
  POST /admin/login          password login
  GET  /admin/oidc/login     redirect to the OIDC provider
  GET  /admin/oidc/callback  code exchange, create session
  POST /admin/logout         destroy session

Env vars: ADMIN_USERNAME (default "admin"), ADMIN_PASSWORD,
OIDC_DISCOVERY_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET.
The admin panel is enabled when a password or OIDC is configured.
"""

import hmac
import os
import secrets
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import DATA_DIR, load_config

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

OIDC_DISCOVERY_URL = os.getenv("OIDC_DISCOVERY_URL", "")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")

password_enabled = bool(ADMIN_PASSWORD)
oidc_enabled = bool(OIDC_DISCOVERY_URL and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET)
admin_enabled = password_enabled or oidc_enabled

_LOGIN_HTML = Path(__file__).parent / "static" / "admin" / "login.html"


def secret_key() -> str:
    """Session signing key: SECRET_KEY env var or generated once into the data dir."""
    if os.getenv("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = DATA_DIR / ".secret_key"
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key)
        path.chmod(0o600)
        return key


oauth = OAuth()
if oidc_enabled:
    oauth.register(
        name="oidc",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        server_metadata_url=OIDC_DISCOVERY_URL,
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",  # PKCE
        },
    )


def _safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _root(request: Request) -> str:
    """Mount prefix of the admin app, e.g. /admin."""
    return request.scope.get("root_path", "")


def _callback_uri(request: Request) -> str:
    # Absolute URL; scheme and host come from proxy headers via
    # ProxyHeadersMiddleware, and base_url already includes the mount prefix
    return str(request.base_url).rstrip("/") + "/oidc/callback"


def render_login(error: str = "") -> HTMLResponse:
    cfg = load_config()
    html = _LOGIN_HTML.read_text()
    html = html.replace("__SITE_TITLE__", cfg.site_title)
    html = html.replace("__ERROR__", error)
    html = html.replace("__ERROR_HIDDEN__", "" if error else "hidden")
    html = html.replace("__PASSWORD_HIDDEN__", "" if password_enabled else "hidden")
    html = html.replace("__DIVIDER_HIDDEN__", "" if (password_enabled and oidc_enabled) else "hidden")
    html = html.replace("__OIDC_HIDDEN__", "" if oidc_enabled else "hidden")
    return HTMLResponse(html, status_code=401 if error else 200)


router = APIRouter()


@router.get("/login")
async def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse(_root(request) + "/")
    return render_login()


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = str(form.get("username", ""))
    password = str(form.get("password", ""))
    if password_enabled and _safe_equal(username, ADMIN_USERNAME) and _safe_equal(password, ADMIN_PASSWORD):
        request.session.clear()
        request.session["admin"] = {"name": username, "via": "password"}
        return RedirectResponse(_root(request) + "/", status_code=303)
    return render_login("Invalid credentials")


@router.get("/oidc/login")
async def oidc_login(request: Request):
    if not oidc_enabled:
        return RedirectResponse(_root(request) + "/login")
    if request.session.get("admin"):
        return RedirectResponse(_root(request) + "/")
    try:
        return await oauth.oidc.authorize_redirect(request, _callback_uri(request))
    except Exception as e:
        print(f"OIDC login failed: {e}")
        return render_login("OpenID Connect sign-in failed")


@router.get("/oidc/callback")
async def oidc_callback(request: Request):
    if not oidc_enabled:
        return RedirectResponse(_root(request) + "/login")
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as e:
        print(f"OIDC callback failed: {e}")
        return render_login("OpenID Connect sign-in failed")
    userinfo = token.get("userinfo") or {}
    request.session.clear()
    request.session["admin"] = {
        "name": userinfo.get("name")
        or userinfo.get("preferred_username")
        or userinfo.get("email")
        or userinfo.get("sub", ""),
        "via": "oidc",
    }
    return RedirectResponse(_root(request) + "/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(_root(request) + "/login", status_code=303)
