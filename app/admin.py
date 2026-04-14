import io
import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import CONFIG_DIR, LEGAL_DIR, LOGS_DIR, Config, load_config, save_config

try:
    import pillow_avif  # noqa: F401 - registers AVIF encoder
except ImportError:
    pass

from PIL import Image

app = FastAPI()

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
        p = CONFIG_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None


def _logo_pending_path() -> Path | None:
    for ext in ("avif", "webp"):
        p = CONFIG_DIR / f"logo_pending.{ext}"
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


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("__VERSION__", APP_VERSION)
    return HTMLResponse(html)


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
    data["has_favicon"] = (CONFIG_DIR / "favicon-32.png").exists()
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

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Clear any previous pending files
    for other in ("avif", "webp"):
        p = CONFIG_DIR / f"logo_pending.{other}"
        if p.exists():
            p.unlink()

    pending = CONFIG_DIR / f"logo_pending.{ext}"
    pending.write_bytes(buf.getvalue())
    _dlog("logo upload: saved pending %s (%dx%d from %dx%d, ratio=%.2f)", pending, new_w, new_h, w, h, ratio)
    return {"ok": True, "preview_url": "/api/logo/pending"}


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
        live = CONFIG_DIR / f"logo.{ext}"
        if live.exists():
            live.unlink()

    live = CONFIG_DIR / f"logo.{p.suffix.lstrip('.')}"
    os.replace(p, live)

    cfg = load_config()
    cfg.header_mode = "logo"
    save_config(cfg)
    _dlog("logo confirm: live=%s", live)
    return {"ok": True}


@app.post("/api/logo/discard")
async def discard_logo():
    for ext in ("avif", "webp"):
        p = CONFIG_DIR / f"logo_pending.{ext}"
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.delete("/api/logo")
async def delete_logo():
    for ext in ("avif", "webp"):
        p = CONFIG_DIR / f"logo.{ext}"
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
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    img.resize((32, 32), Image.LANCZOS).save(CONFIG_DIR / "favicon-32_pending.png", "PNG")
    img.resize((180, 180), Image.LANCZOS).save(CONFIG_DIR / "favicon-180_pending.png", "PNG")
    _dlog("favicon upload: saved pending files")
    return {"ok": True, "preview_url": "/api/favicon/pending"}


@app.get("/api/favicon/pending")
async def favicon_pending():
    path = CONFIG_DIR / "favicon-32_pending.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No pending favicon")
    return FileResponse(str(path), media_type="image/png")


@app.post("/api/favicon/confirm")
async def confirm_favicon():
    p32 = CONFIG_DIR / "favicon-32_pending.png"
    p180 = CONFIG_DIR / "favicon-180_pending.png"
    if not p32.exists():
        raise HTTPException(status_code=404, detail="No pending favicon to confirm")

    os.replace(p32, CONFIG_DIR / "favicon-32.png")
    if p180.exists():
        os.replace(p180, CONFIG_DIR / "favicon-180.png")
    _dlog("favicon confirm: live files updated")
    return {"ok": True}


@app.post("/api/favicon/discard")
async def discard_favicon():
    for name in ("favicon-32_pending.png", "favicon-180_pending.png"):
        p = CONFIG_DIR / name
        if p.exists():
            p.unlink()
    return {"ok": True}


@app.delete("/api/favicon")
async def delete_favicon():
    for name in ("favicon-32.png", "favicon-180.png"):
        p = CONFIG_DIR / name
        if p.exists():
            p.unlink()
    _dlog("favicon deleted")
    return {"ok": True}


# ── Stats / Logs (stubs -- replaced when request logging is implemented) ───────

@app.get("/api/stats")
async def get_stats():
    return {"available": False, "message": "Request logging not yet configured"}


@app.get("/api/logs")
async def get_logs(page: int = 1, per_page: int = 50):
    return {
        "available": False,
        "message": "Request logging not yet configured",
        "items": [],
        "total": 0,
        "pages": 0,
        "page": page,
    }


# Static files -- mounted last so API routes take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
