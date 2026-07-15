"""Session auth for the admin panel: username/password plus optional OIDC.

The OIDC flow and its config storage (oauth.json, managed from the admin UI,
restart required to apply) are ported from social-downloader and adapted to
Starlette. Routes, config fields and login page layout are unified with
nyshare's admin auth:

  GET  /admin/login          login page
  POST /admin/login          password login
  GET  /admin/oidc/login     redirect to the OIDC provider
  GET  /admin/oidc/callback  code exchange, create session
  POST /admin/logout         destroy session

Password login comes from ADMIN_USERNAME/ADMIN_PASSWORD env vars (also the
lockout fallback when OIDC breaks). OIDC is configured in the admin panel
under Authentication and stored in DATA_DIR/oauth.json. The admin panel is
enabled when a password or OIDC is configured.
"""

import hmac
import json
import os
import secrets
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import DATA_DIR, load_config

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

_OAUTH_CONFIG_PATH = DATA_DIR / "oauth.json"

OAUTH_DEFAULTS = {
    "enabled": False,
    "client_id": "",
    "client_secret": "",
    "discovery_url": "",
    "session_lifetime_days": 7,
    # Public base URL of this service (e.g. https://dl.example.com); used for
    # the OIDC redirect URL and available for future external links
    "external_url": "",
}


def get_oauth_config() -> dict:
    """Read oauth.json and merge with defaults. Safe to call frequently."""
    try:
        with open(_OAUTH_CONFIG_PATH) as f:
            data = json.load(f)
        return {**OAUTH_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(OAUTH_DEFAULTS)


def save_oauth_config(cfg: dict) -> None:
    """Persist oauth.json atomically."""
    _OAUTH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_OAUTH_CONFIG_PATH) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, _OAUTH_CONFIG_PATH)


# Captured at import time; a restart is required for oauth.json changes to
# take effect (the Authentication settings UI says so).
_oauth_cfg = get_oauth_config()

password_enabled = bool(ADMIN_PASSWORD)
oidc_enabled = bool(
    _oauth_cfg["enabled"]
    and _oauth_cfg["discovery_url"]
    and _oauth_cfg["client_id"]
    and _oauth_cfg["client_secret"]
)
admin_enabled = password_enabled or oidc_enabled
session_days = max(1, min(365, int(_oauth_cfg.get("session_lifetime_days", 7) or 7)))

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
        client_id=_oauth_cfg["client_id"],
        client_secret=_oauth_cfg["client_secret"],
        server_metadata_url=_oauth_cfg["discovery_url"],
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
    # Prefer the configured external URL; fall back to the request, where
    # scheme and host come from proxy headers via ProxyHeadersMiddleware
    # (base_url already includes the /admin mount prefix)
    ext = get_oauth_config()["external_url"].rstrip("/")
    if ext:
        return ext + "/admin/oidc/callback"
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
