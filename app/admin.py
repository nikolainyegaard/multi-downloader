import logging
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import CONFIG_DIR, LOGS_DIR, Config, load_config, save_config

app = FastAPI()

STATIC_DIR = Path(__file__).parent / "static" / "admin"
APP_VERSION = os.getenv("APP_VERSION", "dev")

# Dev-mode file logger: one log file per container run, written to the config volume
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


class ConfigUpdate(BaseModel):
    site_title: str = "multi-downloader"
    subtitle: str = "Paste a link, download the video"
    accent_color: str = "#3b82f6"
    show_paste_button: bool = True
    custom_logo: bool = False
    kofi_username: str = ""


@app.get("/")
async def root():
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("__VERSION__", APP_VERSION)
    return HTMLResponse(html)


@app.get("/api/config")
async def get_config():
    cfg = load_config()
    _dlog("GET /api/config  returned=%s", asdict(cfg))
    return asdict(cfg)


@app.post("/api/config")
async def set_config(data: ConfigUpdate):
    payload = data.model_dump()
    _dlog("POST /api/config  received=%s", payload)
    cfg = Config(**payload)
    _dlog("POST /api/config  saving=%s", asdict(cfg))
    save_config(cfg)
    _dlog("POST /api/config  saved ok")
    return {"ok": True}


@app.post("/api/config/reset")
async def reset_config():
    _dlog("POST /api/config/reset")
    save_config(Config())
    return {"ok": True}


# Static files -- mounted last so API routes take priority
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
