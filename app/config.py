import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

DATA_DIR          = Path(os.getenv("DATA_DIR", "/app/data"))
CONFIG_DIR        = DATA_DIR / "config"
LEGAL_DIR         = DATA_DIR / "legal"
LOGS_DIR          = DATA_DIR / "logs"
STATIC_ASSETS_DIR = DATA_DIR / "static"
CONFIG_FILE       = CONFIG_DIR / "config.json"

_FIELDS = frozenset({
    "site_title", "subtitle", "accent_color", "show_paste_button",
    "header_mode", "kofi_enabled", "kofi_username", "browser_title", "show_disclaimer_warning",
})


@dataclass
class Config:
    site_title: str = "multi-downloader"
    subtitle: str = "Paste a link, download the video"
    accent_color: str = "#3b82f6"
    show_paste_button: bool = True
    header_mode: str = "title"   # "title" | "logo"
    kofi_enabled: bool = False
    kofi_username: str = ""
    browser_title: str = ""
    show_disclaimer_warning: bool = True


def load_config() -> Config:
    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return Config()
    return Config(**{k: v for k, v in raw.items() if k in _FIELDS})


def migrate_from_legacy() -> None:
    """
    One-time migration from the pre-v0.3.0 flat ./config bind mount to the
    ./data subdirectory structure. Safe to call on every startup: does nothing
    when the legacy path does not exist or the destination is already populated.

    To use: temporarily add the old bind mount alongside the new one in
    docker-compose.yml (e.g. add a read-only - ./config:/app/config:ro entry),
    start the container once, then remove the old bind mount.

    If CONFIG_DIR was customised via the old CONFIG_DIR env var, set
    LEGACY_CONFIG_DIR to that path and restart.
    """
    legacy_root = Path(os.getenv("LEGACY_CONFIG_DIR", "/app/config"))
    if not legacy_root.exists():
        return

    candidates = [
        (legacy_root / "config.json",   CONFIG_DIR / "config.json",   "config"),
        (legacy_root / "disclaimer.md", LEGAL_DIR  / "disclaimer.md", "legal"),
    ]

    migrated = []
    for src, dst, label in candidates:
        if not src.exists():
            continue
        if dst.exists():
            print(f"[migration] skipping {label}: {dst} already exists", flush=True)
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            migrated.append((src, dst))
            print(f"[migration] copied {src} -> {dst}", flush=True)
        except Exception as exc:
            print(f"[migration] could not copy {src} -> {dst}: {exc}", flush=True)

    if migrated:
        print(
            "[migration] done. Old files left in place. "
            "Once verified, remove the old bind mount (./config) from docker-compose.yml.",
            flush=True,
        )


def migrate_assets_to_static() -> None:
    """
    One-time migration: move logo/favicon asset files from data/config/ to data/static/.
    Safe to call on every startup: skips files that already exist at the destination.
    """
    asset_names = [
        "logo.avif", "logo.webp",
        "logo_pending.avif", "logo_pending.webp",
        "favicon-32.png", "favicon-180.png",
        "favicon-32_pending.png", "favicon-180_pending.png",
    ]
    moved = []
    for name in asset_names:
        src = CONFIG_DIR / name
        if not src.exists():
            continue
        dst = STATIC_ASSETS_DIR / name
        if dst.exists():
            print(f"[migration] skipping {name}: already at {dst}", flush=True)
            continue
        try:
            STATIC_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dst)
            moved.append(name)
            print(f"[migration] moved {src} -> {dst}", flush=True)
        except Exception as exc:
            print(f"[migration] could not move {src} -> {dst}: {exc}", flush=True)
    if moved:
        print(f"[migration] assets moved to data/static/: {', '.join(moved)}", flush=True)


def save_config(cfg: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_DIR / "config.json.tmp"
    tmp.write_text(json.dumps(asdict(cfg), indent=2))
    os.replace(tmp, CONFIG_FILE)
