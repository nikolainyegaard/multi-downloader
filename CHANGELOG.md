# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Cookies management in the admin panel Content tab: upload, replace, or delete a Netscape-format cookies.txt passed to yt-dlp on every download; enables sites that need a login, such as NSFW posts on X. Uploads are validated and take effect immediately
- Built-in admin login: username/password via ADMIN_USERNAME and ADMIN_PASSWORD, plus optional OpenID Connect via OIDC_DISCOVERY_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET
- Log out button in the admin sidebar

### Changed
- Admin panel moved from a separate ADMIN_MODE container on its own subdomain (behind Authentik) to /admin inside the main app; one container, one domain, sessions last 7 days

### Removed
- ADMIN_MODE env var and the second compose service; the Authentik forward_auth requirement is gone

### Security
- Visitor-submitted URLs and forwarded IPs are now escaped before rendering in the admin logs table and statistics legend, closing a stored XSS in the admin panel

### Fixed
- Single-stream downloads are remuxed to MP4 as intended; the previous remux option was silently ignored by the yt-dlp Python API
- `data/cookies.txt` is now actually passed to yt-dlp; it was documented but never wired up
- Request log writes are awaited instead of fired as untracked tasks, so entries can no longer be dropped mid-write
- Logs API clamps `page` and `per_page`; `page=0` previously produced an invalid negative query offset
- Save button no longer stays visible forever after saving an accent color typed in uppercase

### Changed
- Public page refresh: accent-tinted backdrop, card shadow, focus rings on the URL field and buttons, hover and press feedback on the download button, preview card fade-in
- Clear button in the URL field appears whenever there is text, not only for invalid URLs; it turns red only when the URL is invalid

## [0.3.0] - 2026-04-18

### Added
- Quality selector: split download button with a chevron-triggered dropdown listing available resolutions (e.g. 1080p, 720p, 480p); defaults to highest available
- Download progress percentage shown in the button during file transfer
- Preview metadata fetch triggers on keystroke with a 600ms debounce, in addition to paste
- URL validation on the input field: red border and a clear button appear for non-http/https input
- `bgutil-ytdlp-pot-provider` sidecar generates YouTube Proof of Origin tokens without a logged-in account, restoring YouTube downloads blocked by bot detection
- Per-domain concurrency limit (max 2 simultaneous yt-dlp operations per platform) to reduce rate-limit exposure
- Logo upload in the admin panel: AVIF or WebP, transparent padding trimmed, aspect ratio validated (1:1 to 5:1), scaled to fit 480x160
- Favicon upload in the admin panel: center-cropped to square, saved at 32x32 and 180x180 PNG
- `header_mode` config field: `"logo"` shows the uploaded logo in the page header, `"title"` shows the site title text (default)
- `browser_title` config field: sets the browser tab title independently of the visible site title
- `show_disclaimer_warning` config field: dismissible banner in the admin panel when `disclaimer.md` is absent; reset to `true` by "Reset to defaults"
- `/disclaimer-guide` page on the admin app with setup steps for the legal disclaimer file
- Per-field reset buttons in admin branding and content forms
- Custom confirm dialog for destructive admin actions (logo delete, favicon delete, config reset)
- Request logging: every `/api/info` and `/api/download` call written to `data/db/requests.db` with timestamp, IP, country, browser, OS, device type, endpoint, URL, success flag, filename, file size, duration, and error detail; logging failures never interrupt a download
- Country resolution from IP via `GeoLite2-Country.mmdb` if placed in `data/db/`; column is null when the file is absent
- Admin statistics tab: total request, download, and error counts; platform breakdown pie chart; stacked daily downloads/errors bar chart (14 days); both charts have hover tooltips
- Admin logs tab: paginated request log table with timestamp, IP, country, platform, endpoint, duration, and status
- Dark/light/system theme toggle on the admin page; shares `localStorage` with the public page so the preference persists across both
- Accent color applied throughout the admin UI (hue derived from configured color); updates live when saved
- Floating save button in admin appears only when the current form section has unsaved changes; hidden immediately after saving
- `/assets/` route on both public and admin apps serves `data/static/` directly

### Fixed
- Admin statistics charts redraw continuously during window resize, matching the display refresh rate; previously the canvas would warp until resizing stopped

### Changed
- Data directory restructured: flat `./config` bind mount replaced by `./data` with subdirectories (`config/`, `legal/`, `logs/`, `db/`, `static/`); `CONFIG_DIR` env var replaced by `DATA_DIR` (default `/app/data`); `disclaimer.md` moves to `legal/`; dev-mode admin logs move to `logs/`
- `/api/info` response now includes a `qualities` array (`label`, `height`) derived from yt-dlp format info
- `/api/download` now accepts an optional `height` field; omitting it or passing `null` selects best available quality
- Logo and favicon asset files stored in `data/static/` rather than `data/config/`; `config/` now holds only `config.json`; startup migration moves existing files automatically
- Public container data volume changed from `:ro` to read-write to support request logging
- Page content is top-aligned rather than vertically centered
- yt-dlp uses a browser-like User-Agent, 30s socket timeout, 3 retries, 5 fragment retries, and a 0.5s inter-request sleep to reduce rate-limit exposure
- Minimum yt-dlp version pinned to `2025.05.22`
- `docker-compose.yml`: added `bgutil-provider` service and `downloader_net` internal network; downloader containers attach to both `caddy_net` and `downloader_net`

  **Breaking change for existing deployments:** update the bind mount in `docker-compose.yml` from `./config:/app/config` to `./data:/app/data`. To use the automatic migration, add the old mount alongside the new one for first boot, then remove it.

## [0.2.0] - 2026-04-12

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

[Unreleased]: https://github.com/nikolainyegaard/multi-downloader/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nikolainyegaard/multi-downloader/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/nikolainyegaard/multi-downloader/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nikolainyegaard/multi-downloader/releases/tag/v0.1.0
