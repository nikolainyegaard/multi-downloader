# multi-downloader

A mobile-focused web app for downloading videos from any* source.

Paste a link, tap Download, get the file. Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

*(\*1000+ supported sites; limitations may apply for login-gated content)*

---

## Setup

### 1. Get the docker-compose file

Create a folder on your server and drop in a `docker-compose.yml`.

**Without admin panel** (single container, simpler):

```yaml
services:
  multi-downloader:
    image: ghcr.io/nikolainyegaard/multi-downloader:latest
    container_name: multi-downloader
    restart: unless-stopped
    environment:
      TZ: "Europe/Oslo"
    ports:
      - "127.0.0.1:8000:8000"
```

**With admin panel** (two containers, config volume; see [Admin panel](#admin-panel)):

```yaml
services:
  multi-downloader:
    image: ghcr.io/nikolainyegaard/multi-downloader:latest
    container_name: multi-downloader
    restart: unless-stopped
    environment:
      TZ: "Europe/Oslo"
    volumes:
      - config:/app/config:ro
    expose:
      - "8000"
    networks:
      - caddy_net

  multi-downloader-admin:
    image: ghcr.io/nikolainyegaard/multi-downloader:latest
    container_name: multi-downloader-admin
    restart: unless-stopped
    environment:
      TZ: "Europe/Oslo"
      ADMIN_MODE: "1"
    volumes:
      - config:/app/config:rw
    expose:
      - "8000"
    networks:
      - caddy_net

volumes:
  config:

networks:
  caddy_net:
    external: true
```

### 2. Start the containers

```bash
docker compose up -d
```

The app will be available at `http://localhost:8000` (or via your reverse proxy).

### 3. Use it

1. Copy a video URL (YouTube, Twitter/X, TikTok, Instagram, Vimeo, and [1000+ more](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md))
2. Tap **Paste** or paste the URL into the input field
3. Tap **Download** and the file downloads directly to your device

> **Note:** The Paste button uses the browser Clipboard API, which requires a secure context (HTTPS or localhost). Caddy handles TLS automatically; no extra configuration needed.

---

## Caddy integration

If Caddy runs directly on the host (not in Docker):

```caddy
dl.yourdomain.com {
    reverse_proxy localhost:8000
}
```

If Caddy is a Docker container on the same host, attach the downloader to Caddy's network and drop the `ports` block (already done in the two-container compose above):

```caddy
dl.yourdomain.com {
    reverse_proxy multi-downloader:8000
}
```

---

## Admin panel

The admin panel runs as a second container from the same image. It exposes a settings UI for branding and content; changes take effect immediately without restarting the main container.

Access is gated by [Authentik](https://goauthentik.io/) via Caddy `forward_auth`. No auth code lives in the app itself.

**Caddyfile:**
```caddy
dl.yourdomain.com {
    reverse_proxy multi-downloader:8000
}

admin-dl.yourdomain.com {
    forward_auth authentik:9000 {
        uri /outpost.goauthentik.io/auth/caddy
        copy_headers X-authentik-username X-authentik-groups
    }
    reverse_proxy multi-downloader-admin:8000
}
```

Settings available in the admin UI:

| Setting | Description |
|---|---|
| Site title | Displayed in the browser tab and page header |
| Subtitle | Tagline below the title |
| Accent color | Color picker for buttons and highlights |
| Footer text | Text in the page footer |
| Show Paste button | Toggle the Paste button on/off |

Settings are stored in `/app/config/config.json` on the shared Docker volume. The public container mounts the volume read-only.

---

## Configuration

Environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|---|---|---|
| `TZ` | `UTC` | Container timezone for log timestamps, e.g. `Europe/Oslo`. |
| `WEB_PORT` | `8000` | Port the app listens on inside the container. |
| `ADMIN_MODE` | unset | Set to `1` to run the container as the admin panel instead of the public site. |
| `CONFIG_DIR` | `/app/config` | Path to the config volume mount point. |

---

## Local development

Requires Python 3.10+ and [ffmpeg](https://ffmpeg.org/).

```bash
pip install -r requirements.txt

# Public site
uvicorn app.main:app --reload

# Admin panel
ADMIN_MODE=1 uvicorn app.main:app --reload --port 8001
```

Open `http://localhost:8000` (public) or `http://localhost:8001` (admin).

---

## Building and publishing the image

```bash
docker buildx build \
  --build-arg BUILD_VERSION=vX.Y.Z \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/nikolainyegaard/multi-downloader:latest \
  -t ghcr.io/nikolainyegaard/multi-downloader:vX.Y.Z \
  --push .
```

To authenticate with GHCR, see the [GitHub docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
