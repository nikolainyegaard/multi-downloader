import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import Config, load_config, save_config

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static" / "admin"
APP_VERSION = os.getenv("APP_VERSION", "dev")


class ConfigUpdate(BaseModel):
    site_title: str = "multi-downloader"
    subtitle: str = "Paste a link, download the video"
    accent_color: str = "#3b82f6"
    footer_text: str = "Powered by yt-dlp"
    show_paste_button: bool = True
    custom_logo: bool = False


@app.get("/")
async def root():
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("__VERSION__", APP_VERSION)
    return HTMLResponse(html)


@app.get("/api/config")
async def get_config():
    return asdict(load_config())


@app.post("/api/config")
async def set_config(data: ConfigUpdate):
    save_config(Config(**data.model_dump()))
    return {"ok": True}


@app.post("/api/config/reset")
async def reset_config():
    save_config(Config())
    return {"ok": True}


# Static files -- mounted last so API routes take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
