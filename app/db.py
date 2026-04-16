import asyncio
from datetime import datetime, timezone

import aiosqlite
import geoip2.database
import geoip2.errors
from ua_parser import user_agent_parser

from app.config import DATA_DIR

DB_DIR     = DATA_DIR / "db"
DB_PATH    = DB_DIR / "requests.db"
GEOIP_PATH = DB_DIR / "GeoLite2-Country.mmdb"

_TABLET_FAMILIES = frozenset({
    "iPad", "Kindle", "Kindle Fire", "BlackBerry Playbook", "Generic Tablet",
})

_geoip_reader: geoip2.database.Reader | None = None

_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS requests (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT NOT NULL,
        ip          TEXT,
        country     TEXT,
        user_agent  TEXT,
        browser     TEXT,
        os          TEXT,
        device_type TEXT,
        endpoint    TEXT,
        url         TEXT,
        success     INTEGER,
        error       TEXT,
        filename    TEXT,
        filesize    INTEGER,
        duration_ms INTEGER
    )
"""


def _get_country(ip: str) -> str | None:
    if _geoip_reader is None:
        return None
    try:
        return _geoip_reader.country(ip).country.iso_code
    except Exception:
        return None


def _parse_ua(ua_string: str) -> tuple[str | None, str | None, str | None]:
    if not ua_string:
        return None, None, None
    parsed = user_agent_parser.Parse(ua_string)

    ua = parsed["user_agent"]
    browser = ua["family"]
    if ua["major"]:
        browser = f"{browser} {ua['major']}"

    os_data = parsed["os"]
    os_name = os_data["family"]
    if os_data["major"]:
        os_name = f"{os_name} {os_data['major']}"

    device_family = (parsed["device"]["family"] or "").strip()
    if device_family == "Other":
        device_type = "desktop"
    elif device_family in _TABLET_FAMILIES or "tablet" in device_family.lower():
        device_type = "tablet"
    else:
        device_type = "mobile"

    return browser, os_name, device_type


async def init_db() -> None:
    global _geoip_reader

    DB_DIR.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_TABLE)
        await db.commit()

    if GEOIP_PATH.exists():
        try:
            _geoip_reader = geoip2.database.Reader(str(GEOIP_PATH))
        except Exception:
            pass


def close_db() -> None:
    global _geoip_reader
    if _geoip_reader is not None:
        try:
            _geoip_reader.close()
        except Exception:
            pass
        _geoip_reader = None


async def log_request(
    *,
    ip: str,
    user_agent: str,
    endpoint: str,
    url: str,
    success: bool,
    error: str | None = None,
    filename: str | None = None,
    filesize: int | None = None,
    duration_ms: int,
) -> None:
    try:
        country = _get_country(ip)
        browser, os_name, device_type = _parse_ua(user_agent)
        ts = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO requests
                    (ts, ip, country, user_agent, browser, os, device_type,
                     endpoint, url, success, error, filename, filesize, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts, ip, country, user_agent, browser, os_name, device_type,
                    endpoint, url, 1 if success else 0, error,
                    filename, filesize, duration_ms,
                ),
            )
            await db.commit()
    except Exception:
        pass
