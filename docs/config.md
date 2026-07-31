# Configuration, data layout, Docker

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TZ` | UTC | Container timezone for log timestamps (e.g. `Europe/Oslo`) |
| `WEB_PORT` | `8000` | uvicorn listen port inside the container |
| `DATA_DIR` | `/app/data` | Path to the data volume mount point inside the container |
| `AUTH_RESET` | unset | Set to `1` and restart: disables OIDC, regenerates admin credentials and prints them to the container output. Remove after signing in |
| `SECRET_KEY` | auto | Session signing key; generated once into `data/.secret_key` if unset |
| `BGUTIL_URL` | `http://bgutil-provider:4416` | URL of the bgutil PO token provider sidecar |
| `LEGACY_CONFIG_DIR` | `/app/config` | Source path for the one-time pre-v0.3.0 config migration (see below) |
| `APP_VERSION` | `dev` | Injected at build time via the `BUILD_VERSION` ARG; not set manually |

## Data volume

Bind mount `./data`, mounted at `/app/data` (override with `DATA_DIR`). The container mounts it read-write because it writes `data/db/requests.db`; config safety relies on the admin UI being the only writer of `config.json`, not on an OS-level `:ro` mount.

```
/app/data/
  .secret_key         session signing key (auto-generated; or SECRET_KEY env)
  oauth.json          login settings: OIDC config + hashed admin credentials
  config/
    config.json       all settings (schema below)
  legal/
    disclaimer.md     legal disclaimer (optional; enables /legal-disclaimer when present)
  logs/               dev-mode admin debug logs (auto-created when APP_VERSION starts with "dev")
  db/
    requests.db       SQLite request log (auto-created)
    GeoLite2-Country.mmdb   optional; enables country resolution
  static/             uploaded logo/favicon assets; served at /assets/
  cookies.txt         optional; Netscape-format cookies passed to yt-dlp per call
  cookies.timestamp   upload time of cookies.txt (st_mtime unreliable on volume mounts)
```

If `config.json` is absent, `load_config()` returns built-in defaults; a fresh deployment with no volume works out of the box.

## Config schema (`config.json`)

```json
{
  "site_title": "multi-downloader",
  "subtitle": "Paste a link, download the video",
  "accent_color": "#3b82f6",
  "show_paste_button": true,
  "header_mode": "title",
  "kofi_enabled": false,
  "kofi_username": "",
  "browser_title": "",
  "show_disclaimer_warning": true
}
```

Fields are intentionally narrow. Extend as needed, but read the `ConfigUpdate` gotcha in [gotchas.md](gotchas.md) first: a new field must be added in three places.

Notes:

- `load_config()` reads from disk on every request; no in-memory cache, no stale state after a save
- `save_config()` writes atomically via `.tmp` + `os.replace()`; the public app never reads a partial file
- `header_mode` is `"title"` or `"logo"`; logo confirm/delete in the admin panel flips it
- `show_disclaimer_warning` backs the dismissible admin banner shown when `disclaimer.md` is absent; "Reset to defaults" intentionally sets it back to `true` (fresh start)
- Accent color is injected as an inline `<style>` block: the public page uses the hex directly with a `color-mix()` hover shade; the admin page extracts the hue and derives hsl variables

## Startup migrations

Both are safe to run on every startup and skip anything already migrated:

- `migrate_from_legacy()` (called from `main.py`): one-time copy from the pre-v0.3.0 flat `./config` bind mount (`config.json`, `disclaimer.md`) into the `./data` structure. To use it, temporarily add the old bind mount read-only alongside the new one (`- ./config:/app/config:ro`), start once, then remove it. If the old `CONFIG_DIR` env var was customised, set `LEGACY_CONFIG_DIR` to that path
- `migrate_assets_to_static()` (lifespan): moves logo/favicon files from `data/config/` to `data/static/`

## Docker and GHCR

**Image:** `ghcr.io/nikolainyegaard/multi-downloader`. **Base:** `python:3.12-slim`. **Port:** 8000 (internal only; compose uses `expose`, not `ports`).

Build notes:
- `ffmpeg` installed via apt (required by yt-dlp for muxing and the MP4 remux postprocessor)
- `ARG BUILD_VERSION=dev` / `ENV APP_VERSION=${BUILD_VERSION}` (injected at build time)
- Only `app/` is copied into the image; the repo's `config/` folder is not part of it

## Compose networks

- `caddy_net` (external): Caddy routes traffic to the downloader container via this network
- `downloader_net`: internal-only bridge between the app and `bgutil-provider`; not reachable from outside this stack. `bgutil-provider` sits on `downloader_net` only, so it has no path to `caddy_net`

## Caddy

Docker Caddy (container on `caddy_net`, matching this repo's docker-compose.yml):
```caddy
dl.yourdomain.com {
    reverse_proxy multi-downloader:8000
}
```

Host Caddy (binary on the server; requires publishing the port, e.g. `127.0.0.1:8000:8000` as in the README's compose example):
```caddy
dl.yourdomain.com {
    reverse_proxy localhost:8000
}
```

No forward_auth; auth lives in the app. The OIDC redirect URL registered with the provider is `https://dl.yourdomain.com/admin/oidc/callback` (built from the configured external URL, falling back to the request, where the scheme comes from `X-Forwarded-Proto` via ProxyHeadersMiddleware).
