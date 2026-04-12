# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Admin panel via second container from the same image (`ADMIN_MODE=1`): branding (site title, subtitle, accent color), content (paste button toggle, Ko-fi widget), and a reset-to-defaults action
- `GET /api/config`, `POST /api/config`, `POST /api/config/reset` endpoints (admin mode only)
- `config.json` written atomically to a bind mount (`./config`) at `/app/config/`; public container mounts it read-only, admin container read-write
- Public site applies config values to the HTML response on every request; no restart needed after a save
- Accent color injected as an inline `<style>` block; hover shade derived via `color-mix()`; no hardcoded hover hex
- Ko-fi support widget: set `kofi_username` in the admin panel to enable; leave empty to disable
- Version and GitHub repo link shown in the page footer for all builds
- Legal disclaimer page at `/legal-disclaimer`: rendered from `config/disclaimer.md` (Markdown); returns 404 if the file is absent; a notice linking to it appears on the main page when the file exists
- System/Light/Dark theme toggle, fixed top-right; preference saved in `localStorage`; defaults to System (follows OS `prefers-color-scheme`); applies to the legal disclaimer page as well

### Changed
- Downloaded files are now named `{service}-{uploader}-{id}.mp4` (e.g. `yt-LinusTechTips-dQw4w9WgXcQ.mp4`); common platforms use short tags (`yt`, `ig`, `tt`, `x`); unknown platforms fall back to the yt-dlp extractor name
- Single-stream downloads are now remuxed to MP4 without re-encoding, closing the gap where a `best` fallback could produce a non-MP4 file
- Static files moved from `app/static/` into `app/static/public/`; `app/static/admin/` added for admin UI
- `main.py` is now a 4-line entry point; logic split into `public.py` and `admin.py`
- `docker-compose.yml` updated: two services (`multi-downloader` + `multi-downloader-admin`) sharing a bind-mount config volume (`./config`), both attached to `caddy_net`; `volumes:` section removed
- `footer_text` config field removed; the footer area is now used for the disclaimer notice (shown only when `config/disclaimer.md` exists)

### Fixed
- Preview card no longer appears as an empty box while metadata is loading; the card stays hidden until title, meta, and thumbnail data have been received
- Clicking Download before the preview loads no longer prevents the preview from appearing; the metadata request now runs in parallel with the download

## [0.1.0] - 2026-04-11

### Added
- Mobile-first single-page web frontend with URL input, Paste button, and Download button
- Video preview (thumbnail, title, duration, uploader) triggered on paste or URL input
- FastAPI backend with streaming download endpoint (`POST /api/download`)
- Metadata endpoint (`POST /api/info`) for video preview lookups
- yt-dlp integration as primary download engine; ffmpeg used for format muxing
- Input field cleared when download begins; preview and status banner auto-dismiss after 3 seconds
- Static file cache-busting via `APP_VERSION` build arg baked into query strings
- Static files served from the FastAPI process; no separate web server required
- Docker image published to GHCR (`ghcr.io/nikolainyegaard/multi-downloader`), multiplatform (amd64 + arm64)
- `docker-compose.yml` for deployment behind Caddy reverse proxy
- `BUILD_VERSION` build arg baked into image as `APP_VERSION` env var

[Unreleased]: https://github.com/nikolainyegaard/multi-downloader/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nikolainyegaard/multi-downloader/releases/tag/v0.1.0
