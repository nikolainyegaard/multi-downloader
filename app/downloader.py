import os
import yt_dlp


def download_video(url: str, output_dir: str) -> str:
    """
    Download a video to output_dir using yt-dlp.
    Returns the absolute path of the downloaded file.
    Raises yt_dlp.utils.DownloadError on failure.
    """
    opts = {
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        # Prefer a pre-muxed MP4; fall back to best available and mux to MP4.
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        try:
            return info["requested_downloads"][0]["filepath"]
        except (KeyError, IndexError):
            # Fallback: derive path from prepared filename
            return ydl.prepare_filename(info)
