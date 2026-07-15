import io
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import aiosqlite
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.config import CONFIG_DIR, DATA_DIR, LEGAL_DIR, LOGS_DIR, STATIC_ASSETS_DIR, Config, load_config, migrate_assets_to_static, save_config
from app.db import DB_PATH, init_db

try:
    import pillow_avif  # noqa: F401 - registers AVIF encoder
except ImportError:
    pass

from PIL import Image


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate_assets_to_static()
    await init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(auth.router)

# Paths inside the /admin mount that never require a session
_PUBLIC_PATHS = {"/login", "/oidc/login", "/oidc/callback", "/favicon.ico"}


@app.middleware("http")
async def require_admin(request: Request, call_next):
    # Path relative to the /admin mount; newer Starlette keeps the full path
    # in scope["path"] and only sets root_path
    root = request.scope.get("root_path", "")
    path = request.scope["path"]
    if root and path.startswith(root):
        path = path[len(root):] or "/"
    if path in _PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    if not auth.admin_enabled():
        return JSONResponse(
            {"detail": "Admin panel disabled: no login method is configured. Set AUTH_RESET=1 and restart to regenerate credentials."},
            status_code=404,
        )
    if not request.session.get("admin"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse(request.scope.get("root_path", "") + "/login")
    return await call_next(request)


# Added after require_admin so it wraps it and sessions are available inside
app.add_middleware(
    SessionMiddleware,
    secret_key=auth.secret_key(),
    session_cookie="mdl_admin",
    max_age=auth.session_days * 24 * 3600,
    same_site="lax",
)


# ── Authentication settings API ────────────────────────────────────────────────
# OIDC config lives in DATA_DIR/oauth.json and is edited from the
# Authentication section. Changes apply after a container restart.

class AuthConfigUpdate(BaseModel):
    enabled: bool = False
    discovery_url: str = ""
    client_id: str = ""
    client_secret: str = ""  # blank keeps the stored secret
    session_lifetime_days: int = 7
    external_url: str = ""
    password_login: bool = True
    admin_username: str = "admin"
    new_password: str = ""  # blank keeps the stored password


@app.get("/api/auth/config")
async def get_auth_config():
    cfg = auth.get_oauth_config()
    return {
        "enabled": cfg["enabled"],
        "enabled_runtime": auth.oidc_enabled,
        "client_id": cfg["client_id"],
        "client_secret_set": bool(cfg["client_secret"]),
        "discovery_url": cfg["discovery_url"],
        "session_lifetime_days": cfg["session_lifetime_days"],
        "external_url": cfg["external_url"],
        "password_login": cfg["password_login"],
        "admin_username": cfg["admin_username"],
        "password_set": bool(cfg["admin_password_hash"]),
        "must_change_password": cfg["must_change_password"],
    }


@app.post("/api/auth/config")
async def save_auth_config(update: AuthConfigUpdate):
    cfg = auth.get_oauth_config()
    cfg["enabled"] = update.enabled
    cfg["discovery_url"] = update.discovery_url.strip()
    cfg["client_id"] = update.client_id.strip()
    if update.client_secret:
        cfg["client_secret"] = update.client_secret.strip()
    cfg["session_lifetime_days"] = max(1, min(365, update.session_lifetime_days or 7))
    cfg["external_url"] = update.external_url.strip().rstrip("/")
    cfg["password_login"] = update.password_login
    if update.admin_username.strip():
        cfg["admin_username"] = update.admin_username.strip()
    if update.new_password:
        if len(update.new_password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        cfg["admin_password_hash"] = auth.hash_password(update.new_password)
        cfg["must_change_password"] = False

    if cfg["enabled"] and not all([cfg["client_id"], cfg["client_secret"], cfg["discovery_url"]]):
        raise HTTPException(
            status_code=400,
            detail="Discovery URL, client ID and client secret are all required to enable OIDC",
        )
    if not cfg["enabled"] and not cfg["password_login"]:
        raise HTTPException(status_code=400, detail="At least one login method must stay enabled")
    if not cfg["password_login"] and not auth.oidc_enabled:
        # Guard against saving into a lockout: OIDC must already be running
        # (saved, restarted and active) before password login can be turned off
        raise HTTPException(
            status_code=400,
            detail="Enable OIDC and restart the container before disabling password login",
        )

    auth.save_oauth_config(cfg)
    return {"ok": True, "restart_required": True}

STATIC_DIR = Path(__file__).parent / "static" / "admin"
APP_VERSION = os.getenv("APP_VERSION", "dev")

# Dev-mode file logger
_log: logging.Logger | None = None
if APP_VERSION.startswith("dev"):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_path = LOGS_DIR / f"admin_debug_{_ts}.log"
    _handler = logging.FileHandler(_log_path)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _log = logging.getLogger("admin_debug")
    _log.setLevel(logging.DEBUG)
    _log.addHandler(_handler)
    _log.info("admin started  version=%s  config_dir=%s  log=%s", APP_VERSION, CONFIG_DIR, _log_path)


def _dlog(msg: str, *args) -> None:
    if _log:
        _log.info(msg, *args)


def _logo_path() -> Path | None:
    for ext in ("avif", "webp"):
        p = STATIC_ASSETS_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None


def _logo_pending_path() -> Path | None:
    for ext in ("avif", "webp"):
        p = STATIC_ASSETS_DIR / f"logo_pending.{ext}"
        if p.exists():
            return p
    return None


def _crop_square(img: Image.Image) -> Image.Image:
    """Center-crop an image to a square. Used for favicons."""
    w, h = img.size
    side = min(w, h)
    return img.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))


def _trim_logo(img: Image.Image) -> Image.Image:
    """
    Trim transparent padding from logos. Palette images are converted to RGBA first
    so their transparency index is resolved. Opaque RGB images are returned as-is
    because whitespace trimming without transparency is unreliable.
    """
    if img.mode in ("P", "PA"):
        img = img.convert("RGBA")
    if img.mode not in ("RGBA", "LA"):
        return img
    alpha = img.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return img  # fully transparent, nothing to trim
    return img.crop(bbox)


# Logo sizing constants
_LOGO_MAX_W   = 480
_LOGO_MAX_H   = 160
_LOGO_MIN_RATIO = 1.0   # must be at least as wide as tall (landscape or square)
_LOGO_MAX_RATIO = 5.0   # wider than 5:1 is a banner, not a logo


class ConfigUpdate(BaseModel):
    site_title: str = "multi-downloader"
    subtitle: str = "Paste a link, download the video"
    accent_color: str = "#3b82f6"
    show_paste_button: bool = True
    header_mode: str = "title"   # "title" | "logo"
    kofi_enabled: bool = False
    kofi_username: str = ""
    browser_title: str = ""
    show_disclaimer_warning: bool = True


def _hex_to_hue(hex_color: str) -> int:
    """Extract hue (0-359) from a hex color string."""
    h = hex_color.lstrip('#')
    r = int(h[0:2], 16) / 255
    g = int(h[2:4], 16) / 255
    b = int(h[4:6], 16) / 255
    max_c, min_c = max(r, g, b), min(r, g, b)
    if max_c == min_c:
        return 0
    d = max_c - min_c
    if max_c == r:
        hue = (g - b) / d + (6 if g < b else 0)
    elif max_c == g:
        hue = (b - r) / d + 2
    else:
        hue = (r - g) / d + 4
    return round(hue / 6 * 360)


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    cfg = load_config()
    browser_title = cfg.browser_title if cfg.browser_title else cfg.site_title

    hue = _hex_to_hue(cfg.accent_color)
    accent_style = (
        f"<style>:root {{"
        f" --accent: hsl({hue}, 78%, 60%);"
        f" --accent-hover: hsl({hue}, 78%, 68%);"
        f" --accent-subtle: hsla({hue}, 78%, 60%, 0.10);"
        f" }}</style>"
    )

    favicon_link = ""
    if (STATIC_ASSETS_DIR / "favicon-32.png").exists():
        favicon_link = (
            f'<link rel="icon" type="image/png" sizes="32x32" href="/favicon.ico?v={APP_VERSION}" />\n  '
            f'<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v={APP_VERSION}" />'
        )

    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("__VERSION__", APP_VERSION)
    html = html.replace("__BROWSER_TITLE__", f"Admin - {browser_title}")
    html = html.replace("__ACCENT_STYLE__", accent_style)
    html = html.replace("__FAVICON_LINK__", favicon_link)
    return HTMLResponse(html)


@app.get("/favicon.ico")
async def favicon():
    path = STATIC_ASSETS_DIR / "favicon-32.png"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type="image/png")


@app.get("/apple-touch-icon.png")
async def apple_touch_icon():
    path = STATIC_ASSETS_DIR / "favicon-180.png"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type="image/png")


@app.get("/disclaimer-guide")
async def disclaimer_guide():
    page = (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        '<title>Disclaimer setup</title>'
        '<link rel="stylesheet" href="/static/style.css?v=' + APP_VERSION + '" />'
        '</head><body><div class="guide-page">'
        '<h1>Legal disclaimer setup</h1>'
        '<p>Create the file <code>data/legal/disclaimer.md</code> on your bind-mounted volume '
        'to enable the disclaimer notice on the public site and the <code>/legal-disclaimer</code> page.</p>'
        '<h2>Steps</h2>'
        '<ol>'
        '<li>On the host, create <code>./data/legal/disclaimer.md</code> in your deployment folder.</li>'
        '<li>Write your disclaimer in Markdown. The file is rendered as HTML.</li>'
        '<li>Reload the public site. The notice appears automatically when the file exists.</li>'
        '</ol>'
        '<h2>Removing the notice</h2>'
        '<p>Delete or empty the file. The notice and <code>/legal-disclaimer</code> route '
        'are both suppressed when the file is absent or empty.</p>'
        '</div></body></html>'
    )
    return HTMLResponse(page)


# ── Config API ─────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    cfg = load_config()
    data = asdict(cfg)
    # Computed read-only fields
    data["has_logo"] = _logo_path() is not None
    data["has_favicon"] = (STATIC_ASSETS_DIR / "favicon-32.png").exists()
    data["has_disclaimer"] = (LEGAL_DIR / "disclaimer.md").exists()
    _dlog("GET /api/config  returned=%s", data)
    return data


@app.post("/api/config")
async def set_config(data: ConfigUpdate):
    payload = data.model_dump()
    _dlog("POST /api/config  received=%s", payload)
    cfg = Config(**payload)
    save_config(cfg)
    _dlog("POST /api/config  saved ok")
    return {"ok": True}


@app.post("/api/config/reset")
async def reset_config():
    _dlog("POST /api/config/reset")
    save_config(Config())
    return {"ok": True}


@app.post("/api/dismiss-disclaimer-warning")
async def dismiss_disclaimer_warning():
    cfg = load_config()
    cfg.show_disclaimer_warning = False
    save_config(cfg)
    return {"ok": True}


# ── Logo API ───────────────────────────────────────────────────────────────────

@app.post("/api/logo/upload")
async def upload_logo(file: UploadFile = File(...)):
    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read image file")

    # Trim transparent padding before measuring dimensions
    img = _trim_logo(img)
    w, h = img.size

    if w == 0 or h == 0:
        raise HTTPException(status_code=400, detail="Image is empty after trimming")

    ratio = w / h
    if ratio < _LOGO_MIN_RATIO:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Logo must be wider than it is tall (got {w}x{h}, "
                f"{ratio:.2f}:1 aspect ratio). Upload a horizontal or square logo."
            ),
        )
    if ratio > _LOGO_MAX_RATIO:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Logo aspect ratio {ratio:.1f}:1 exceeds the 5:1 maximum (got {w}x{h}). "
                f"Crop the logo to remove excess empty space on the sides."
            ),
        )

    # Scale to fit within 480x160, preserving aspect ratio; never upscale
    scale = min(_LOGO_MAX_W / w, _LOGO_MAX_H / h, 1.0)
    new_w = max(1, round(w * scale))
    new_h = max(1, round(h * scale))
    img = img.convert("RGBA").resize((new_w, new_h), Image.LANCZOS)

    # Try AVIF, fall back to WebP
    buf = io.BytesIO()
    ext = "avif"
    try:
        img.save(buf, format="AVIF", quality=70)
    except Exception:
        buf = io.BytesIO()
        ext = "webp"
        img.save(buf, format="WEBP", quality=75)

    STATIC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    # Clear any previous pending files
    for other in ("avif", "webp"):
        p = STATIC_ASSETS_DIR / f"logo_pending.{other}"
        if p.exists():
            p.unlink()

    pending = STATIC_ASSETS_DIR / f"logo_pending.{ext}"
    pending.write_bytes(buf.getvalue())
    _dlog("logo upload: saved pending %s (%dx%d from %dx%d, ratio=%.2f)", pending, new_w, new_h, w, h, ratio)
    return {"ok": True, "preview_url": "/api/logo/pending"}


@app.get("/api/logo")
async def serve_logo():
    logo = _logo_path()
    if not logo:
        raise HTTPException(status_code=404)
    media = "image/avif" if logo.suffix == ".avif" else "image/webp"
    return FileResponse(str(logo), media_type=media)


@app.get("/api/logo/pending")
async def logo_pending():
    p = _logo_pending_path()
    if not p:
        raise HTTPException(status_code=404, detail="No pending logo")
    media = "image/avif" if p.suffix == ".avif" else "image/webp"
    return FileResponse(str(p), media_type=media)


@app.post("/api/logo/confirm")
async def confirm_logo():
    p = _logo_pending_path()
    if not p:
        raise HTTPException(status_code=404, detail="No pending logo to confirm")

    # Remove existing live logo (any format)
    for ext in ("avif", "webp"):
        live = STATIC_ASSETS_DIR / f"logo.{ext}"
        if live.exists():
            live.unlink()

    live = STATIC_ASSETS_DIR / f"logo.{p.suffix.lstrip('.')}"
    os.replace(p, live)

    cfg = load_config()
    cfg.header_mode = "logo"
    save_config(cfg)
    _dlog("logo confirm: live=%s", live)
    return {"ok": True}


@app.post("/api/logo/discard")
async def discard_logo():
    for ext in ("avif", "webp"):
        p = STATIC_ASSETS_DIR / f"logo_pending.{ext}"
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.delete("/api/logo")
async def delete_logo():
    for ext in ("avif", "webp"):
        p = STATIC_ASSETS_DIR / f"logo.{ext}"
        if p.exists():
            p.unlink()
    cfg = load_config()
    cfg.header_mode = "title"
    save_config(cfg)
    _dlog("logo deleted")
    return {"ok": True}


# ── Favicon API ────────────────────────────────────────────────────────────────

@app.post("/api/favicon/upload")
async def upload_favicon(file: UploadFile = File(...)):
    data = await file.read()
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read image file")

    img = _crop_square(img)
    STATIC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    img.resize((32, 32), Image.LANCZOS).save(STATIC_ASSETS_DIR / "favicon-32_pending.png", "PNG")
    img.resize((180, 180), Image.LANCZOS).save(STATIC_ASSETS_DIR / "favicon-180_pending.png", "PNG")
    _dlog("favicon upload: saved pending files")
    return {"ok": True, "preview_url": "/api/favicon/pending"}


@app.get("/api/favicon/pending")
async def favicon_pending():
    path = STATIC_ASSETS_DIR / "favicon-32_pending.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No pending favicon")
    return FileResponse(str(path), media_type="image/png")


@app.post("/api/favicon/confirm")
async def confirm_favicon():
    p32 = STATIC_ASSETS_DIR / "favicon-32_pending.png"
    p180 = STATIC_ASSETS_DIR / "favicon-180_pending.png"
    if not p32.exists():
        raise HTTPException(status_code=404, detail="No pending favicon to confirm")

    os.replace(p32, STATIC_ASSETS_DIR / "favicon-32.png")
    if p180.exists():
        os.replace(p180, STATIC_ASSETS_DIR / "favicon-180.png")
    _dlog("favicon confirm: live files updated")
    return {"ok": True}


@app.post("/api/favicon/discard")
async def discard_favicon():
    for name in ("favicon-32_pending.png", "favicon-180_pending.png"):
        p = STATIC_ASSETS_DIR / name
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.delete("/api/favicon")
async def delete_favicon():
    for name in ("favicon-32.png", "favicon-180.png"):
        p = STATIC_ASSETS_DIR / name
        if p.exists():
            p.unlink()
    _dlog("favicon deleted")
    return {"ok": True}


# ── Cookies API ────────────────────────────────────────────────────────────────
# The public app passes data/cookies.txt to yt-dlp on every call, so uploads
# apply immediately. Upload time lives in a companion file because st_mtime is
# unreliable on Docker volume mounts.
# ponytail: one shared cookies.txt for all sites (yt-dlp filters by domain);
# split into per-service files if cross-site cookie separation ever matters.

COOKIES_FILE  = DATA_DIR / "cookies.txt"
COOKIES_STAMP = DATA_DIR / "cookies.timestamp"


def _cookies_info() -> dict:
    if not COOKIES_FILE.exists():
        return {"present": False}
    try:
        updated_at = int(COOKIES_STAMP.read_text().strip())
    except (FileNotFoundError, ValueError):
        updated_at = None
    return {
        "present": True,
        "size_bytes": COOKIES_FILE.stat().st_size,
        "updated_at": updated_at,
    }


@app.get("/api/cookies")
async def get_cookies():
    return _cookies_info()


@app.post("/api/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)):
    data = await file.read()
    text = data.decode("utf-8", errors="ignore")
    # Sanity check: at least one Netscape cookie line (7 tab-separated fields,
    # allowing the #HttpOnly_ prefix). Catches HTML exports and JSON dumps.
    lines = (l.removeprefix("#HttpOnly_") for l in text.splitlines())
    if not any(len(l.split("\t")) == 7 for l in lines if l.strip() and not l.startswith("#")):
        raise HTTPException(
            status_code=400,
            detail="Not a Netscape-format cookies.txt. Export one with a browser extension like Get cookies.txt LOCALLY.",
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_DIR / "cookies.txt.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, COOKIES_FILE)
    COOKIES_STAMP.write_text(str(int(time.time())))
    _dlog("cookies upload: %d bytes", len(data))
    return {"ok": True, **_cookies_info()}


@app.delete("/api/cookies")
async def delete_cookies():
    for p in (COOKIES_FILE, COOKIES_STAMP):
        if p.exists():
            p.unlink()
    _dlog("cookies deleted")
    return {"ok": True}


# ── Stats / Logs ──────────────────────────────────────────────────────────────

def _platform(url: str | None) -> str | None:
    if not url:
        return None
    try:
        netloc = urlparse(url).netloc
        # strip www. prefix for display
        return netloc.removeprefix("www.") or None
    except Exception:
        return None


@app.get("/api/stats")
async def get_stats():
    if not DB_PATH.exists():
        return {"available": False}

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        row = await (await db.execute(
            "SELECT COUNT(*) AS total FROM requests"
        )).fetchone()
        total_requests = row["total"]

        row = await (await db.execute(
            "SELECT COUNT(*) AS total FROM requests WHERE endpoint = 'download' AND success = 1"
        )).fetchone()
        total_downloads = row["total"]

        row = await (await db.execute(
            "SELECT COUNT(*) AS total FROM requests WHERE success = 0"
        )).fetchone()
        total_errors = row["total"]

        rows = await (await db.execute(
            """
            SELECT url, COUNT(*) AS cnt
            FROM requests
            WHERE endpoint = 'download' AND success = 1 AND url IS NOT NULL
            GROUP BY url
            """
        )).fetchall()

        daily_rows = await (await db.execute(
            """
            SELECT
                substr(ts, 1, 10) AS date,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS ok,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS err
            FROM requests
            WHERE endpoint = 'download'
            GROUP BY date
            ORDER BY date DESC
            LIMIT 14
            """
        )).fetchall()

    platform_counts: dict[str, int] = {}
    for r in rows:
        p = _platform(r["url"])
        if p:
            platform_counts[p] = platform_counts.get(p, 0) + r["cnt"]

    services = sorted(
        [{"name": k, "count": v} for k, v in platform_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    daily = [{"date": r["date"], "ok": r["ok"], "err": r["err"]} for r in reversed(daily_rows)]

    return {
        "available": True,
        "totals": [
            {"label": "Total requests", "value": total_requests},
            {"label": "Downloads", "value": total_downloads},
            {"label": "Errors", "value": total_errors},
        ],
        "services": services,
        "daily": daily,
    }


@app.get("/api/logs")
async def get_logs(page: int = 1, per_page: int = 50):
    page = max(1, page)
    per_page = min(max(1, per_page), 500)

    if not DB_PATH.exists():
        return {"available": False, "items": [], "total": 0, "pages": 0, "page": page}

    offset = (page - 1) * per_page

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        row = await (await db.execute("SELECT COUNT(*) AS total FROM requests")).fetchone()
        total = row["total"]

        rows = await (await db.execute(
            """
            SELECT ts, ip, country, endpoint, url, success, duration_ms
            FROM requests
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        )).fetchall()

    items = [
        {
            "ts": r["ts"],
            "ip": r["ip"],
            "country": r["country"],
            "endpoint": r["endpoint"],
            "platform": _platform(r["url"]),
            "url": r["url"],
            "success": bool(r["success"]),
            "duration_ms": r["duration_ms"],
        }
        for r in rows
    ]

    return {
        "available": True,
        "items": items,
        "total": total,
        "pages": max(1, math.ceil(total / per_page)),
        "page": page,
    }


# User-provided assets (logos, favicons, etc.) served from data/static/
STATIC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=STATIC_ASSETS_DIR), name="user_assets")

# Bundled app static files -- mounted last so API routes take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
