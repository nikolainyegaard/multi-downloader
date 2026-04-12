import os
import re
import yt_dlp

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


def get_video_info(url: str) -> dict:
    """
    Fetch metadata for a URL without downloading.
    Returns a dict with title, thumbnail, duration, uploader, qualities.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    opts = {
        **_COMMON_OPTS,
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
    if height is not None:
        fmt = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
            f"/best[height<={height}][ext=mp4]"
            f"/best[height<={height}]"
        )
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    opts = {
        **_COMMON_OPTS,
        # Use a simple unique name during download; renamed to the final format after.
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "format": fmt,
        "merge_output_format": "mp4",
        # Remux single-stream downloads to MP4 without re-encoding.
        "remux_video": "mp4",
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
