import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.downloader import download_video

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static"


class DownloadRequest(BaseModel):
    url: str


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


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
        # Strip yt-dlp's "ERROR: " prefix for a cleaner message
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

    # RFC 5987 encoding so unicode titles survive the header
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


# Static files — mounted last so API routes always take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
