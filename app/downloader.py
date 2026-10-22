import json
import os
import re
import zipfile
from urllib.parse import parse_qs, urlparse

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
    # Multi-video posts (an X tweet quoting another video tweet, for example) come
    # back as a playlist. Honour a /video/N index in the URL, otherwise take the
    # first item; the result is unwrapped by _single() so callers see one video.
    "noplaylist": True,
    "playlist_items": "1",
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


def _single(info: dict) -> dict:
    """Unwrap a playlist result to its only entry. A playlist dict has no formats
    and no ext, so reading it as a video silently produces a .NA filename."""
    if info.get("_type") == "playlist" or "entries" in info:
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise DownloadError("No video could be found in this post")
        return entries[0]
    return info


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


# ── Photo posts ───────────────────────────────────────────────────────────────
# yt-dlp does not download images, so photo posts get bespoke scrapers that
# find the image URLs and fetch them directly (approach adapted from
# social-downloader's photo downloads). Both scrapers are credential-free.
# Delivery is shared: a single image as-is, multiple images as a ZIP.

_EXT_BY_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "video/mp4": "mp4",
}


def _fetch_images(urls: list[str], base: str, output_dir: str, headers: dict) -> str:
    """Download media URLs and package them: one file as {base}.{ext},
    several as {base}.zip (ZIP_STORED, the files are already compressed).
    Returns the absolute path of the output file."""

    def fetch(img_url: str, idx: int) -> tuple[bytes, str]:
        try:
            resp = httpx.get(img_url, headers=headers, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise DownloadError(f"Failed to download photo {idx}/{len(urls)}: {e}")
        content_type = resp.headers.get("content-type", "").split(";")[0].strip()
        return resp.content, _EXT_BY_TYPE.get(content_type, "jpg")

    if len(urls) == 1:
        content, ext = fetch(urls[0], 1)
        dest = os.path.join(output_dir, f"{base}.{ext}")
        with open(dest, "wb") as f:
            f.write(content)
        return dest

    dest = os.path.join(output_dir, f"{base}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as zf:
        for i, img_url in enumerate(urls, 1):
            content, ext = fetch(img_url, i)
            zf.writestr(f"{base}_{i:02d}.{ext}", content)
    return dest


# ── TikTok photo posts ────────────────────────────────────────────────────────
# yt-dlp's TikTok extractor only matches /video/ URLs; photo posts fail with
# "Unsupported URL". The main photo page bot-walls plain HTTP clients, but the
# embed page (tiktok.com/embed/v2/{id}) serves the photo data to anyone, no
# login cookies or TLS fingerprint checks.

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
    """Download a TikTok photo post to output_dir; see _fetch_images for
    the delivery format. Raises DownloadError on failure."""
    data = _photo_data(post_id)
    urls = _image_urls(data)
    if not urls:
        raise DownloadError("Photo post contains no downloadable images")
    author = data.get("authorInfos") or {}
    uploader = author.get("uniqueId") or author.get("nickName") or "unknown"
    return _fetch_images(urls, f"tt-{_safe(uploader)}-{_safe(post_id)}", output_dir, _BROWSER_HEADERS)


# ── YouTube community posts ───────────────────────────────────────────────────
# yt-dlp does not support /post/ URLs. The post page is public and serves
# ytInitialData to plain clients; the SOCS=CAI cookie skips the EU consent
# redirect. Image thumbnails are square-cropped WebP previews, but rewriting
# the trailing =s{size}... params to =s0 returns the full-resolution original.

_YT_POST_RE = re.compile(r"^/post/([\w-]+)")
_YT_IMG_SIZE_RE = re.compile(r"=s\d+[^/]*$")

_PLAIN_HEADERS = {
    "User-Agent": _COMMON_OPTS["http_headers"]["User-Agent"],
    "Accept-Language": "en-US,en;q=0.9",
}


def youtube_post_id(url: str) -> str | None:
    """Post ID if this is a YouTube community post URL, else None. Matches
    both youtube.com/post/{id} and the channel community tab's ?lb={id}."""
    parts = urlparse(url)
    bare = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    if bare != "youtube.com":
        return None
    match = _YT_POST_RE.match(parts.path)
    if match:
        return match.group(1)
    if "/community" in parts.path:
        lb = parse_qs(parts.query).get("lb")
        if lb:
            return lb[0]
    return None


def _find_key(obj, key: str):
    """Depth-first search for a key anywhere in nested dicts/lists; the path
    to the post renderer inside ytInitialData is not stable."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            if (found := _find_key(v, key)) is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            if (found := _find_key(v, key)) is not None:
                return found
    return None


def _youtube_post(post_id: str) -> dict:
    """Fetch a community post page and return its backstagePostRenderer dict.
    Raises DownloadError on any failure."""
    try:
        resp = httpx.get(
            f"https://www.youtube.com/post/{post_id}",
            headers=_PLAIN_HEADERS, cookies={"SOCS": "CAI"},
            follow_redirects=True, timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise DownloadError(f"Could not fetch the community post page: {e}")
    match = re.search(r"ytInitialData\s*=\s*({.+?});</script>", resp.text)
    if not match:
        raise DownloadError("Could not find post data on the page (post may be private or removed)")
    post = _find_key(json.loads(match.group(1)), "backstagePostRenderer")
    if not post:
        raise DownloadError("Could not find post data on the page (post may be private or removed)")
    return post


def _youtube_image_urls(post: dict) -> list[str]:
    attachment = post.get("backstageAttachment") or {}
    renderers = [
        img.get("backstageImageRenderer") or {}
        for img in (attachment.get("postMultiImageRenderer") or {}).get("images", [])
    ] or [attachment.get("backstageImageRenderer") or {}]
    urls = []
    for renderer in renderers:
        thumbs = (renderer.get("image") or {}).get("thumbnails") or []
        if thumbs:
            urls.append(_YT_IMG_SIZE_RE.sub("=s0", thumbs[-1]["url"]))
    return urls


def get_youtube_post_info(post_id: str) -> dict:
    """Community post equivalent of get_video_info; same response shape."""
    post = _youtube_post(post_id)
    images = _youtube_image_urls(post)
    text = "".join(run.get("text", "") for run in (post.get("contentText") or {}).get("runs", []))
    author = "".join(run.get("text", "") for run in (post.get("authorText") or {}).get("runs", []))
    return {
        "title": text or "YouTube community post",
        "thumbnail": images[0] if images else None,
        "duration": None,
        "uploader": author or None,
        "qualities": [],
    }


def download_youtube_post(post_id: str, output_dir: str) -> str:
    """Download a YouTube community post's images to output_dir; see
    _fetch_images for the delivery format. Raises DownloadError on failure."""
    post = _youtube_post(post_id)
    urls = _youtube_image_urls(post)
    if not urls:
        raise DownloadError("Post contains no downloadable images")
    author = "".join(run.get("text", "") for run in (post.get("authorText") or {}).get("runs", [])) or "unknown"
    return _fetch_images(urls, f"yt-{_safe(author)}-{_safe(post_id)}", output_dir, _PLAIN_HEADERS)


# ── Instagram and X photo posts (gallery-dl fallback) ─────────────────────────
# yt-dlp cannot download images, so Instagram posts and X photo tweets that
# fail yt-dlp extraction fall back to gallery-dl, which resolves the post's
# media URLs. X works logged out (NSFW tweets need cookies); Instagram
# redirects to a login page unless cookies.txt holds Instagram cookies.
# The cookies file is passed on every call, so uploads need no restart.
# Mixed carousels are handled: video entries land in the ZIP alongside images.

_GALLERY_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:instagram\.com/(?:[\w.]+/)?(?:p|reel|tv)/|(?:twitter|x)\.com/\w+/status/\d+)"
)


def _gallery_media(url: str) -> tuple[list[str], dict]:
    """Resolve a post's media URLs and metadata via gallery-dl.
    Raises DownloadError on failure or when the post has no media."""
    from gallery_dl import config as gdl_config
    from gallery_dl import extractor as gdl_extractor
    from gallery_dl.extractor.message import Message

    cookies = DATA_DIR / "cookies.txt"
    gdl_config.set(("extractor",), "cookies", str(cookies) if cookies.exists() else None)
    gdl_config.set(("extractor",), "user-agent", _COMMON_OPTS["http_headers"]["User-Agent"])

    ex = gdl_extractor.find(url)
    if ex is None:
        raise DownloadError("Unsupported URL")
    urls, meta = [], {}
    try:
        for msg in ex:
            if msg[0] == Message.Directory:
                meta = msg[2] or meta
            elif msg[0] == Message.Url:
                meta = meta or msg[2]
                urls.append(msg[1])
    except Exception as e:
        raise DownloadError(f"Could not fetch the post: {e}")
    if not urls:
        raise DownloadError("Post contains no downloadable media")
    meta["category"] = ex.category  # "twitter" / "instagram"; not in the message metadata
    return urls, meta


def _gallery_names(meta: dict) -> tuple[str, str, str]:
    """(service tag, uploader, post id) from gallery-dl metadata. Key names
    differ per extractor: X nests the author under user, Instagram is flat."""
    user = meta.get("user") or {}
    uploader = (
        meta.get("username") or user.get("name") or meta.get("fullname") or user.get("nick") or "unknown"
    )
    post_id = str(meta.get("tweet_id") or meta.get("shortcode") or meta.get("post_shortcode") or "unknown")
    return _service_tag(meta.get("category", "")), uploader, post_id


def get_gallery_info(url: str) -> dict:
    """Gallery post equivalent of get_video_info; same response shape."""
    urls, meta = _gallery_media(url)
    _, uploader, _ = _gallery_names(meta)
    return {
        "title": meta.get("content") or meta.get("description") or "Photo post",
        "thumbnail": urls[0],
        "duration": None,
        "uploader": uploader if uploader != "unknown" else None,
        "qualities": [],
    }


def download_gallery_post(url: str, output_dir: str) -> str:
    """Download an Instagram or X post's media to output_dir; see
    _fetch_images for the delivery format. Raises DownloadError on failure."""
    urls, meta = _gallery_media(url)
    tag, uploader, post_id = _gallery_names(meta)
    return _fetch_images(urls, f"{_safe(tag)}-{_safe(uploader)}-{_safe(post_id)}", output_dir, _PLAIN_HEADERS)


def get_video_info(url: str) -> dict:
    """
    Fetch metadata for a URL without downloading.
    Returns a dict with title, thumbnail, duration, uploader, qualities.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    if post_id := tiktok_photo_id(url):
        return get_photo_info(post_id)
    if post_id := youtube_post_id(url):
        return get_youtube_post_info(post_id)
    opts = {
        **_base_opts(),
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = _single(ydl.extract_info(url, download=False))
            return {
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "duration": info.get("duration"),  # seconds, may be None
                "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
                "qualities": _extract_qualities(info),
            }
    except DownloadError:
        if _GALLERY_URL_RE.match(url):
            try:
                return get_gallery_info(url)
            except DownloadError:
                pass
        raise


def download_video(url: str, output_dir: str, height: int | None = None) -> str:
    """
    Download a video to output_dir using yt-dlp.
    height: cap the video resolution (e.g. 720 for 720p); None means best available.
    Returns the absolute path of the downloaded file.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    if post_id := tiktok_photo_id(url):
        return download_photos(post_id, output_dir)
    if post_id := youtube_post_id(url):
        return download_youtube_post(post_id, output_dir)

    try:
        return _download_via_ytdlp(url, output_dir, height)
    except DownloadError:
        if _GALLERY_URL_RE.match(url):
            try:
                return download_gallery_post(url, output_dir)
            except DownloadError:
                pass
        raise


def _download_via_ytdlp(url: str, output_dir: str, height: int | None) -> str:
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
        info = _single(ydl.extract_info(url, download=True))
        try:
            src = info["requested_downloads"][0]["filepath"]
        except (KeyError, IndexError):
            src = ydl.prepare_filename(info)

        tag = _service_tag(info.get("extractor", ""))
        uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "unknown"
        video_id = info.get("id", "unknown")
        ext = os.path.splitext(src)[1]
        if not os.path.isfile(src):
            # Let the gallery-dl fallback in download_video take over instead of
            # surfacing a FileNotFoundError from the rename below.
            raise DownloadError("No video file was produced for this post")

        dest = os.path.join(output_dir, f"{_safe(tag)}-{_safe(uploader)}-{_safe(video_id)}{ext}")
        os.rename(src, dest)
        return dest
