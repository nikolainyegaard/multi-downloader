import asyncio
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote, urlparse

import mistune
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import CONFIG_DIR, LEGAL_DIR, load_config
from app.downloader import download_video, get_video_info

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static" / "public"
APP_VERSION = os.getenv("APP_VERSION", "dev")

# Limit concurrent yt-dlp operations per platform domain to avoid triggering rate limits.
_domain_semaphores: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(2))


def _domain(url: str) -> str:
    return urlparse(url).netloc or url


def _logo_path() -> Path | None:
    for ext in ("avif", "webp"):
        p = CONFIG_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None


class DownloadRequest(BaseModel):
    url: str
    height: int | None = None


@app.get("/")
async def root():
    cfg = load_config()
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("__VERSION__", APP_VERSION)

    # Browser tab title
    browser_title = cfg.browser_title if cfg.browser_title else cfg.site_title
    html = html.replace("__BROWSER_TITLE__", browser_title)

    html = html.replace("__ACCENT_COLOR__", cfg.accent_color)
    html = html.replace("__PASTE_HIDDEN__", "" if cfg.show_paste_button else " hidden")

    # Favicon links
    if (CONFIG_DIR / "favicon-32.png").exists():
        favicon_link = (
            f'<link rel="icon" type="image/png" sizes="32x32" href="/favicon.ico?v={APP_VERSION}" />\n  '
            f'<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v={APP_VERSION}" />'
        )
    else:
        favicon_link = ""
    html = html.replace("__FAVICON_LINK__", favicon_link)

    # Logo vs text title (mutually exclusive)
    logo = _logo_path()
    if cfg.header_mode == "logo" and logo:
        header_content = (
            f'<img src="/logo?v={APP_VERSION}" class="site-logo" alt="{cfg.site_title}" />\n'
            f'      <p class="subtitle">{cfg.subtitle}</p>'
        )
    else:
        header_content = (
            f'<h1>{cfg.site_title}</h1>\n'
            f'      <p class="subtitle">{cfg.subtitle}</p>'
        )
    html = html.replace("__HEADER_CONTENT__", header_content)

    # Disclaimer notice
    disclaimer_path = LEGAL_DIR / "disclaimer.md"
    if disclaimer_path.exists():
        disclaimer_notice = (
            '<p class="disclaimer-notice">'
            'By downloading, you agree to our '
            '<a href="/legal-disclaimer" target="_blank" rel="noopener">Legal Disclaimer</a>.'
            '</p>'
        )
    else:
        disclaimer_notice = ""
    html = html.replace("__DISCLAIMER_NOTICE__", disclaimer_notice)

    dev_banner = (
        f'<p class="dev-banner">'
        f'{APP_VERSION} &bull; '
        f'<a href="https://github.com/nikolainyegaard/multi-downloader" target="_blank" rel="noopener">GitHub</a>'
        f'</p>'
    )
    html = html.replace("__DEV_BANNER__", dev_banner)

    if cfg.kofi_enabled and cfg.kofi_username:
        kofi_script = (
            f"<script src='https://storage.ko-fi.com/cdn/scripts/overlay-widget.js'></script>\n"
            f"  <script>\n"
            f"    kofiWidgetOverlay.draw('{cfg.kofi_username}', {{\n"
            f"      'type': 'floating-chat',\n"
            f"      'floating-chat.donateButton.text': 'Support me',\n"
            f"      'floating-chat.donateButton.background-color': '#00b9fe',\n"
            f"      'floating-chat.donateButton.text-color': '#fff'\n"
            f"    }});\n"
            f"  </script>"
        )
    else:
        kofi_script = ""
    html = html.replace("__KOFI_SCRIPT__", kofi_script)

    return HTMLResponse(html)


@app.get("/favicon.ico")
async def favicon():
    path = CONFIG_DIR / "favicon-32.png"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type="image/png")


@app.get("/apple-touch-icon.png")
async def apple_touch_icon():
    path = CONFIG_DIR / "favicon-180.png"
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type="image/png")


@app.get("/logo")
async def serve_logo():
    logo = _logo_path()
    if not logo:
        raise HTTPException(status_code=404)
    media = "image/avif" if logo.suffix == ".avif" else "image/webp"
    return FileResponse(str(logo), media_type=media)


@app.get("/legal-disclaimer")
async def legal_disclaimer():
    disclaimer_path = LEGAL_DIR / "disclaimer.md"
    if not disclaimer_path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    content = disclaimer_path.read_text().strip()
    if not content:
        raise HTTPException(status_code=404, detail="Not found")
    cfg = load_config()
    rendered = mistune.html(content)
    page = (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head>'
        '<meta charset="UTF-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0" />'
        '<title>Legal Disclaimer</title>'
        f'<link rel="stylesheet" href="/static/style.css?v={APP_VERSION}" />'
        f'<style>:root {{ --accent: {cfg.accent_color}; --accent-hover: color-mix(in srgb, {cfg.accent_color} 85%, black); }} body {{ justify-content: flex-start; }}</style>'
        "<script>(function(){var t=localStorage.getItem('theme')||'system';document.documentElement.setAttribute('data-theme',t);})()</script>"
        '</head>'
        '<body>'
        '<div class="theme-toggle">'
        '<button class="theme-btn" id="theme-btn" aria-haspopup="true">'
        '<span id="theme-icon" aria-hidden="true"></span>'
        '<span id="theme-label">System</span>'
        '<svg class="theme-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>'
        '</button>'
        '<div class="theme-menu" id="theme-menu" hidden>'
        '<button class="theme-option" data-theme="system">System</button>'
        '<button class="theme-option" data-theme="light">Light</button>'
        '<button class="theme-option" data-theme="dark">Dark</button>'
        '</div>'
        '</div>'
        '<div class="container legal">'
        f'{rendered}'
        '</div>'
        f'<script src="/static/app.js?v={APP_VERSION}"></script>'
        '</body>'
        '</html>'
    )
    return HTMLResponse(page)


@app.post("/api/info")
async def info(req: DownloadRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="URL is required")
    try:
        async with _domain_semaphores[_domain(url)]:
            data = await asyncio.to_thread(get_video_info, url)
        return data
    except yt_dlp.utils.DownloadError as e:
        msg = str(e).removeprefix("ERROR: ")
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download")
async def download(req: DownloadRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="URL is required")

    tmpdir = tempfile.mkdtemp()
    try:
        async with _domain_semaphores[_domain(url)]:
            filepath = await asyncio.to_thread(download_video, url, tmpdir, req.height)
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = str(e).removeprefix("ERROR: ")
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))

    if not os.path.exists(filepath):
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Download produced no output file")

    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    encoded_name = quote(filename, safe="")

    async def stream_and_cleanup():
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return StreamingResponse(
        stream_and_cleanup(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
            "Content-Length": str(filesize),
        },
    )


# Static files -- mounted last so API routes take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
