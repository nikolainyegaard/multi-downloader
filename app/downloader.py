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


def _service_tag(extractor: str) -> str:
    base = extractor.lower().split(":")[0]
    return _SERVICE_TAGS.get(base, base)


def _safe(value: str) -> str:
    # Collapse whitespace to underscores, then strip characters unsafe in filenames.
    value = re.sub(r"\s+", "_", value)
    return re.sub(r"[^\w\-]", "", value) or "unknown"


def get_video_info(url: str) -> dict:
    """
    Fetch metadata for a URL without downloading.
    Returns a dict with title, thumbnail, duration, uploader.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),  # seconds, may be None
            "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        }


def download_video(url: str, output_dir: str) -> str:
    """
    Download a video to output_dir using yt-dlp.
    Returns the absolute path of the downloaded file.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    opts = {
        # Use a simple unique name during download; renamed to the final format after.
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        # Prefer pre-muxed MP4; fall back to best available.
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
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
