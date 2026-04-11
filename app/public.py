import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import load_config
from app.downloader import download_video, get_video_info

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static" / "public"
APP_VERSION = os.getenv("APP_VERSION", "dev")


class DownloadRequest(BaseModel):
    url: str


@app.get("/")
async def root():
    cfg = load_config()
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("__VERSION__", APP_VERSION)
    html = html.replace("__SITE_TITLE__", cfg.site_title)
    html = html.replace("__SUBTITLE__", cfg.subtitle)
    html = html.replace("__ACCENT_COLOR__", cfg.accent_color)
    html = html.replace("__FOOTER_TEXT__", cfg.footer_text)
    html = html.replace("__PASTE_HIDDEN__", "" if cfg.show_paste_button else " hidden")
    return HTMLResponse(html)


@app.post("/api/info")
async def info(req: DownloadRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="URL is required")
    try:
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
        filepath = await asyncio.to_thread(download_video, url, tmpdir)
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
