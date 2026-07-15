# multi-downloader

A mobile-focused web app for downloading videos from any* source.

Paste a link, tap Download, get the file. Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

*(\*1000+ supported sites; limitations may apply for login-gated content)*

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/nikolainyegaard)

---

## Features

- Paste a URL, pick a quality, download the file directly to your device
- Video preview with thumbnail, title, duration, and uploader before downloading
- Quality selector: choose resolution (1080p, 720p, 480p, etc.) or let it default to best available
- YouTube bot detection bypassed via `bgutil-ytdlp-pot-provider` sidecar (no account needed)
- Admin panel at `/admin` with username/password and optional OIDC login: branding, logo/favicon upload, request statistics, and logs
- Optional legal disclaimer page at `/legal-disclaimer` served from a Markdown file
- Light/dark/system theme toggle; persists across the public and admin pages
- Docker image for amd64 and arm64

---

## Setup

### 1. Get the docker-compose file

Create a folder on your server and drop in a `docker-compose.yml`.

```yaml
services:
  bgutil-provider:
    image: brainicism/bgutil-ytdlp-pot-provider:latest
    container_name: bgutil-provider
    restart: unless-stopped
    networks:
      - downloader_net

  multi-downloader:
    image: ghcr.io/nikolainyegaard/multi-downloader:latest
    container_name: multi-downloader
    restart: unless-stopped
    environment:
      ADMIN_USERNAME: "admin"
      ADMIN_PASSWORD: "changeme"
    volumes:
      - ./data:/app/data
    ports:
      - "127.0.0.1:8000:8000"
    networks:
      - downloader_net
    depends_on:
      - bgutil-provider

networks:
  downloader_net:
```

Public site at `http://localhost:8000`, admin at `http://localhost:8000/admin`. Leave out `ADMIN_PASSWORD` (and the OIDC variables) to disable the admin panel entirely.

### 2. Start the containers

```bash
docker compose up -d
```

The app will be available at `http://localhost:8000` (or via your reverse proxy).

### 3. Use it

1. Copy a video URL (YouTube, Twitter/X, TikTok, Instagram, Vimeo, and [1000+ more](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md))
2. Tap **Paste** or paste the URL into the input field
3. Select a quality from the dropdown if needed; defaults to best available
4. Tap **Download** and the file downloads directly to your device

> **Note:** The Paste button uses the browser Clipboard API, which requires a secure context (HTTPS or localhost).

---

## Admin panel

The admin panel lives at `/admin` in the same container and exposes a settings UI for branding, content, statistics, and logs; changes take effect immediately.

### Signing in

Two login methods, either or both:

- **Username/password**: set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in the environment
- **OpenID Connect**: set `OIDC_DISCOVERY_URL`, `OIDC_CLIENT_ID`, and `OIDC_CLIENT_SECRET`; a "OpenID Connect" button appears on the login page. Works with any OIDC provider (Authentik, Keycloak, Pocket ID, ...). Register the redirect URL `https://your-domain/admin/oidc/callback` with the provider.

The admin panel is disabled (404) unless at least one method is configured. Sessions last 7 days.

### Settings

| Setting | Description |
|---|---|
| Site title | Visible page header when header mode is "title" (default) |
| Browser title | Browser tab title; defaults to site title if left empty |
| Subtitle | Tagline below the title or logo |
| Accent color | Color for buttons and highlights |
| Header mode | Show the uploaded logo or the site title text in the header |
| Show Paste button | Toggle the Paste button on/off |
| Ko-fi username | Ko-fi username for the support widget; leave empty to disable |

Settings are stored in `./data/config/config.json` on the shared Docker volume.

### Logo and favicon

Upload a logo (AVIF or WebP, aspect ratio 1:1 to 5:1) or favicon (any image; cropped to square) from the Branding tab. Assets are stored in `./data/static/` and served at `/assets/`. Deleting an asset reverts to the default text title or browser default favicon.

### Cookies

Some sites only serve content to logged-in users; the most common case is NSFW posts on X/Twitter. Upload a Netscape-format `cookies.txt` from the Content tab and it is passed to yt-dlp on every download, taking effect immediately.

To create the file, log in to the site in your browser (for X, also enable "Display media that may contain sensitive content" in settings), then export cookies with an extension like [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc). One file can hold cookies for several sites; yt-dlp only sends the ones matching each download's domain.

### Statistics and logs

The Statistics tab shows total request, download, and error counts; a platform breakdown chart; and a 14-day bar chart of downloads and errors. The Logs tab shows a paginated request log with timestamp, IP, country, platform, duration, and status.

Country resolution requires a `GeoLite2-Country.mmdb` file placed in `./data/db/` (free account at [MaxMind](https://www.maxmind.com/en/geolite2/signup)).

### Legal disclaimer

To show a "By downloading, you agree to our Legal Disclaimer" notice on the public site and serve the disclaimer at `/legal-disclaimer`, create `./data/legal/disclaimer.md` and write your disclaimer in Markdown. Delete the file to remove the notice.

---

## Data directory

```
./data/
  config/
    config.json             # All settings; created automatically on first save
  legal/
    disclaimer.md           # Optional; enables /legal-disclaimer when present
  static/                   # User-uploaded assets (logo, favicon)
  db/
    requests.db             # SQLite request log; created automatically
    GeoLite2-Country.mmdb   # Optional; enables country resolution in logs
  cookies.txt               # Optional; login cookies for yt-dlp, managed from the admin panel
  cookies.timestamp         # Upload time of cookies.txt; managed automatically
```

---

## Configuration

Environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|---|---|---|
| `TZ` | `UTC` | Container timezone for log timestamps, e.g. `Europe/Oslo`. |
| `WEB_PORT` | `8000` | Port the app listens on inside the container. |
| `ADMIN_USERNAME` | `admin` | Username for admin password login. |
| `ADMIN_PASSWORD` | unset | Password for admin login; enables the admin panel when set. |
| `OIDC_DISCOVERY_URL` | unset | OIDC `.well-known/openid-configuration` URL; enables the OpenID Connect login button together with the two variables below. |
| `OIDC_CLIENT_ID` | unset | OIDC client ID. |
| `OIDC_CLIENT_SECRET` | unset | OIDC client secret. |
| `SECRET_KEY` | auto | Session signing key; generated once into `data/.secret_key` if unset. |
| `DATA_DIR` | `/app/data` | Path to the data volume mount point inside the container. |

---

## Local development

Requires Python 3.10+ and [ffmpeg](https://ffmpeg.org/).

```bash
pip install -r requirements.txt
ADMIN_PASSWORD=changeme uvicorn app.main:app --reload
```

Open `http://localhost:8000` (public) or `http://localhost:8000/admin` (admin).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
