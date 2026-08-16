import json
import os
import re
import zipfile
from urllib.parse import urlparse

import httpx
import yt_dlp
from yt_dlp.utils import DownloadError

from app.config import DATA_DIR

# Shorthand tags for common services; anything else falls back to the extractor name.
_SERVICE_TAGS = {
    "youtube": "yt",
    "instagram": "ig",
    "tiktok": "tt",
    "twitter": "x",
    "x": "x",
}

# URL of the bgutil PO token provider sidecar. Override via env var if needed.
_BGUTIL_URL = os.getenv("BGUTIL_URL", "http://bgutil-provider:4416")

# Options shared across all yt-dlp invocations.
_COMMON_OPTS: dict = {
    "quiet": True,
    "no_warnings": True,
    "socket_timeout": 30,
    "retries": 3,
    "fragment_retries": 5,
    "extractor_retries": 3,
    "sleep_interval_requests": 0.5,
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    },
    # bgutil sidecar generates YouTube Proof of Origin tokens without a logged-in account.
    "extractor_args": {
        "youtubepot-bgutilhttp": {
            "base_url": [_BGUTIL_URL],
        },
    },
}


def _base_opts() -> dict:
    """Common opts plus the cookies file, checked per call so drop-in cookies need no restart."""
    opts = dict(_COMMON_OPTS)
    cookies = DATA_DIR / "cookies.txt"
    if cookies.exists():
        opts["cookiefile"] = str(cookies)
    return opts


def _service_tag(extractor: str) -> str:
    base = extractor.lower().split(":")[0]
    return _SERVICE_TAGS.get(base, base)


def _safe(value: str) -> str:
    # Collapse whitespace to underscores, then strip characters unsafe in filenames.
    value = re.sub(r"\s+", "_", value)
    return re.sub(r"[^\w\-]", "", value) or "unknown"


def _extract_qualities(info: dict) -> list[dict]:
    """
    Return available video quality options from yt-dlp format info.
    Each entry: {label, height}. Sorted best-first by height.
    """
    formats = info.get("formats") or []

    video_fmts = [
        f for f in formats
        if f.get("vcodec") not in (None, "none") and (f.get("height") or 0) > 0
    ]
    if not video_fmts:
        return []

    # Best format per height (highest tbr wins).
    by_height: dict[int, dict] = {}
    for f in video_fmts:
        h = f["height"]
        if h not in by_height or (f.get("tbr") or 0) > (by_height[h].get("tbr") or 0):
            by_height[h] = f

    return [{"label": f"{h}p", "height": h} for h in sorted(by_height.keys(), reverse=True)]


# ── TikTok photo posts ────────────────────────────────────────────────────────
# yt-dlp's TikTok extractor only matches /video/ URLs; photo posts fail with
# "Unsupported URL". The main photo page bot-walls plain HTTP clients, but the
# embed page (tiktok.com/embed/v2/{id}) serves the photo data to anyone, no
# login cookies or TLS fingerprint checks. Scrape that and fetch the images
# directly (approach adapted from social-downloader's photo downloads).

_TIKTOK_SHORT_HOSTS = {"vm.tiktok.com", "vt.tiktok.com"}
_PHOTO_ID_RE = re.compile(r"/photo/(\d+)")

_BROWSER_HEADERS = {
    "User-Agent": _COMMON_OPTS["http_headers"]["User-Agent"],
    "Referer": "https://www.tiktok.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


def tiktok_photo_id(url: str) -> str | None:
    """Post ID if this is a TikTok photo post URL, else None. Share links
    (vm/vt.tiktok.com, tiktok.com/t/) are resolved first because they hide
    the /photo/ path behind a redirect."""
    parts = urlparse(url)
    host = parts.netloc.lower()
    bare = host.removeprefix("www.")
    if host in _TIKTOK_SHORT_HOSTS or (bare == "tiktok.com" and parts.path.startswith("/t/")):
        try:
            resp = httpx.get(url, headers=_BROWSER_HEADERS, follow_redirects=True, timeout=15)
            parts = urlparse(str(resp.url))
            bare = parts.netloc.lower().removeprefix("www.")
        except httpx.HTTPError:
            return None
    if bare != "tiktok.com":
        return None
    match = _PHOTO_ID_RE.search(parts.path)
    return match.group(1) if match else None


def _photo_data(post_id: str) -> dict:
    """Fetch a photo post's videoData blob from the TikTok embed page.
    Raises DownloadError on any failure so callers handle photo and video
    posts identically."""
    try:
        resp = httpx.get(
            f"https://www.tiktok.com/embed/v2/{post_id}",
            headers=_BROWSER_HEADERS, follow_redirects=True, timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise DownloadError(f"Could not fetch the photo post page: {e}")
    match = re.search(
        r'<script[^>]+\bid=["\']__FRONTITY_CONNECT_STATE__["\'][^>]*>([^<]+)</script>',
        resp.text,
    )
    if not match:
        raise DownloadError("Could not find post data on the page (post may be private or removed)")
    data = (
        json.loads(match.group(1))
        .get("source", {})
        .get("data", {})
        .get(f"/embed/v2/{post_id}", {})
        .get("videoData", {})
    )
    if not data.get("imagePostInfo"):
        raise DownloadError("No photo data on the page (post may be private or removed)")
    return data


def _image_urls(data: dict) -> list[str]:
    return [
        img["urlList"][0]
        for img in data["imagePostInfo"].get("displayImages", [])
        if img.get("urlList")
    ]


def get_photo_info(post_id: str) -> dict:
    """Photo post equivalent of get_video_info; same response shape."""
    data = _photo_data(post_id)
    images = _image_urls(data)
    author = data.get("authorInfos") or {}
    return {
        "title": (data.get("itemInfos") or {}).get("text") or "TikTok photo post",
        "thumbnail": images[0] if images else None,
        "duration": None,
        "uploader": author.get("uniqueId") or author.get("nickName"),
        "qualities": [],
    }


def download_photos(post_id: str, output_dir: str) -> str:
    """
    Download a TikTok photo post to output_dir.
    A single image is saved as a .jpg; multiple images are bundled into a
    .zip (ZIP_STORED, the images are already compressed JPEGs).
    Returns the absolute path of the output file.
    Raises DownloadError on failure.
    """
    data = _photo_data(post_id)
    urls = _image_urls(data)
    if not urls:
        raise DownloadError("Photo post contains no downloadable images")

    author = data.get("authorInfos") or {}
    uploader = author.get("uniqueId") or author.get("nickName") or "unknown"
    base = f"tt-{_safe(uploader)}-{_safe(post_id)}"

    def fetch(img_url: str, idx: int) -> bytes:
        try:
            resp = httpx.get(img_url, headers=_BROWSER_HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPError as e:
            raise DownloadError(f"Failed to download photo {idx}/{len(urls)}: {e}")

    if len(urls) == 1:
        dest = os.path.join(output_dir, f"{base}.jpg")
        with open(dest, "wb") as f:
            f.write(fetch(urls[0], 1))
        return dest

    dest = os.path.join(output_dir, f"{base}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as zf:
        for i, img_url in enumerate(urls, 1):
            zf.writestr(f"{base}_{i:02d}.jpg", fetch(img_url, i))
    return dest


def get_video_info(url: str) -> dict:
    """
    Fetch metadata for a URL without downloading.
    Returns a dict with title, thumbnail, duration, uploader, qualities.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    if post_id := tiktok_photo_id(url):
        return get_photo_info(post_id)
    opts = {
        **_base_opts(),
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),  # seconds, may be None
            "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
            "qualities": _extract_qualities(info),
        }


def download_video(url: str, output_dir: str, height: int | None = None) -> str:
    """
    Download a video to output_dir using yt-dlp.
    height: cap the video resolution (e.g. 720 for 720p); None means best available.
    Returns the absolute path of the downloaded file.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    if post_id := tiktok_photo_id(url):
        return download_photos(post_id, output_dir)
    if height is not None:
        fmt = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/best[height<={height}][ext=mp4]"
            f"/best[height<={height}]"
        )
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    opts = {
        **_base_opts(),
        # Use a simple unique name during download; renamed to the final format after.
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "format": fmt,
        "merge_output_format": "mp4",
        # Remux single-stream downloads to MP4 without re-encoding. The CLI-style
        # "remux_video" key is silently ignored by the Python API; the postprocessor
        # is the working equivalent and skips files that are already MP4.
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        try:
            src = info["requested_downloads"][0]["filepath"]
        except (KeyError, IndexError):
            src = ydl.prepare_filename(info)

        tag = _service_tag(info.get("extractor", ""))
        uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "unknown"
        video_id = info.get("id", "unknown")
        ext = os.path.splitext(src)[1]

        dest = os.path.join(output_dir, f"{_safe(tag)}-{_safe(uploader)}-{_safe(video_id)}{ext}")
        os.rename(src, dest)
        return dest
