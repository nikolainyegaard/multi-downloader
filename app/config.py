import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "/app/config"))
CONFIG_FILE = CONFIG_DIR / "config.json"

_FIELDS = frozenset(
    {"site_title", "subtitle", "accent_color", "footer_text", "show_paste_button", "custom_logo"}
)


@dataclass
class Config:
    site_title: str = "multi-downloader"
    subtitle: str = "Paste a link, download the video"
    accent_color: str = "#3b82f6"
    footer_text: str = "Powered by yt-dlp"
    show_paste_button: bool = True
    custom_logo: bool = False


def load_config() -> Config:
    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return Config()
    return Config(**{k: v for k, v in raw.items() if k in _FIELDS})


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_DIR / "config.json.tmp"
    tmp.write_text(json.dumps(asdict(cfg), indent=2))
    os.replace(tmp, CONFIG_FILE)
