# multi-downloader

A mobile-focused web app for downloading videos from any* source.

Paste a link, tap Download, get the file. Powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

*(\*1000+ supported sites — limitations may apply for login-gated content)*

---

## Setup

### 1. Get the docker-compose file

Create a folder on your server and drop in a `docker-compose.yml`:

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

### 2. Start the container

```bash
docker compose up -d
```

The app will be available at `http://localhost:8000` (or via your reverse proxy).

### 3. Use it

1. Copy a video URL (YouTube, Twitter/X, TikTok, Instagram, Vimeo, and [1000+ more](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md))
2. Tap **Paste** or paste the URL into the input field
3. Tap **Download** — the file downloads directly to your device

> **Note:** The Paste button uses the browser Clipboard API, which requires a secure context (HTTPS or localhost). Caddy handles TLS automatically — no extra configuration needed.

---

## Caddy integration

If Caddy runs directly on the host (not in Docker):

```caddy
dl.yourdomain.com {
    reverse_proxy localhost:8000
}
```

If Caddy is a Docker container on the same host, attach the downloader to Caddy's network and drop the `ports` block:

**docker-compose.yml**
```yaml
services:
  multi-downloader:
    image: ghcr.io/nikolainyegaard/multi-downloader:latest
    container_name: multi-downloader
    restart: unless-stopped
    environment:
      TZ: "Europe/Oslo"
    expose:
      - "8000"
    networks:
      - caddy_net

networks:
  caddy_net:
    external: true  # must match the name of the network Caddy is on
```

**Caddyfile**
```caddy
dl.yourdomain.com {
    reverse_proxy multi-downloader:8000
}
```

---

## Building and publishing the image

```bash
# Build multiplatform and push to GHCR
docker buildx build \
  --build-arg BUILD_VERSION=vX.Y.Z \
  --platform linux/amd64,linux/arm64 \
  -t ghcr.io/nikolainyegaard/multi-downloader:latest \
  -t ghcr.io/nikolainyegaard/multi-downloader:vX.Y.Z \
  --push .
```

To authenticate with GHCR, see the [GitHub docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

---

## Configuration

All configuration is via environment variables in `docker-compose.yml`.

| Variable | Default | Description |
|---|---|---|
| `WEB_PORT` | `8000` | Port the app listens on inside the container. |
| `TZ` | `UTC` | Container timezone for log timestamps, e.g. `Europe/Oslo`. |

---

## Local development

Requires Python 3.10+ and [ffmpeg](https://ffmpeg.org/).

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
