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

Credentials are stored in DATA_DIR/oauth.json, never in the environment: on
first launch (or with AUTH_RESET=1 set) a random admin password is generated,
printed to the container output, and flagged for change after sign-in. Both
login methods are toggled from the admin panel's Authentication section;
OIDC changes apply after a restart, password changes immediately. The admin
panel is enabled when at least one method is usable.
"""

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import DATA_DIR, load_config

AUTH_RESET = os.getenv("AUTH_RESET", "").lower() in ("1", "true", "yes")

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
    "password_login": True,
    "admin_username": "admin",
    "admin_password_hash": "",
    "must_change_password": False,
}

_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2:{_PBKDF2_ITERATIONS}:{salt.hex()}:{dk.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        _, iterations, salt_hex, hash_hex = stored.split(":")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


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


def _print_credentials(title: str, password: str, footer: str) -> None:
    print("=" * 54, flush=True)
    print(title, flush=True)
    print("  Username: admin", flush=True)
    print(f"  Password: {password}", flush=True)
    print(footer, flush=True)
    print("=" * 54, flush=True)


# Startup: read the config once (OIDC settings need a restart to apply) and
# generate admin credentials when none exist or AUTH_RESET is set.
_oauth_cfg = get_oauth_config()

if AUTH_RESET:
    _oauth_cfg["enabled"] = False
    _oauth_cfg["password_login"] = True
    _pw = secrets.token_urlsafe(12)
    _oauth_cfg["admin_username"] = "admin"
    _oauth_cfg["admin_password_hash"] = hash_password(_pw)
    _oauth_cfg["must_change_password"] = True
    save_oauth_config(_oauth_cfg)
    _print_credentials(
        "AUTH_RESET is set: OIDC disabled, admin credentials reset",
        _pw,
        "Remove AUTH_RESET from the environment after signing in.",
    )
elif _oauth_cfg["password_login"] and not _oauth_cfg["admin_password_hash"]:
    _pw = secrets.token_urlsafe(12)
    _oauth_cfg["admin_password_hash"] = hash_password(_pw)
    _oauth_cfg["must_change_password"] = True
    save_oauth_config(_oauth_cfg)
    _print_credentials(
        "Admin credentials generated (first launch)",
        _pw,
        "Sign in at /admin/login and set a new password in the Authentication section.",
    )

oidc_enabled = bool(
    _oauth_cfg["enabled"]
    and _oauth_cfg["discovery_url"]
    and _oauth_cfg["client_id"]
    and _oauth_cfg["client_secret"]
)
session_days = max(1, min(365, int(_oauth_cfg.get("session_lifetime_days", 7) or 7)))


def password_login_enabled() -> bool:
    """Read fresh: password and username changes apply without a restart."""
    cfg = get_oauth_config()
    return bool(cfg["password_login"] and cfg["admin_password_hash"])


def admin_enabled() -> bool:
    return password_login_enabled() or oidc_enabled

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
    pw = password_login_enabled()
    html = _LOGIN_HTML.read_text()
    html = html.replace("__SITE_TITLE__", cfg.site_title)
    html = html.replace("__ERROR__", error)
    html = html.replace("__ERROR_HIDDEN__", "" if error else "hidden")
    html = html.replace("__PASSWORD_HIDDEN__", "" if pw else "hidden")
    html = html.replace("__DIVIDER_HIDDEN__", "" if (pw and oidc_enabled) else "hidden")
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
    cfg = get_oauth_config()
    if (
        password_login_enabled()
        and _safe_equal(username, cfg["admin_username"])
        and verify_password(cfg["admin_password_hash"], password)
    ):
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
