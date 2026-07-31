# Architecture

Mobile-focused web frontend for downloading videos from any* source, powered by yt-dlp (1000+ supported sites; some need login cookies for private or restricted content). The UX is deliberately minimal: a URL input with a Paste button, a quality selector, and a Download button that delivers the file directly to the user's device. Ships as a Docker image: `ghcr.io/nikolainyegaard/multi-downloader`, fronted by Caddy.

Single-repo app: a Python backend (FastAPI) that also serves the static frontend. One container: the admin app is mounted at `/admin` inside the public app, behind session auth (username/password and/or OIDC). The former `ADMIN_MODE` second container and Authentik forward_auth are gone.

## File structure

```
multi-downloader/
├── app/
│   ├── main.py          entry point; runs the legacy config migration, imports the public app
│   ├── public.py        public FastAPI app: pages + download API + static mounts; mounts admin at /admin
│   ├── admin.py         FastAPI sub-app: auth middleware + config/branding/cookies/stats/logs API
│   ├── auth.py          session auth: password + OIDC (authlib), login routes, oauth.json handling
│   ├── config.py        Config dataclass, load/save helpers, startup migrations
│   ├── db.py            request log (SQLite) + GeoIP and user-agent parsing
│   ├── downloader.py    yt-dlp wrapper: info extraction, quality list, download + MP4 remux
│   └── static/
│       ├── public/      main site frontend (index.html, app.js, style.css)
│       └── admin/       admin UI frontend (index.html, login.html, app.js, style.css)
├── config/
│   └── disclaimer.md    disclaimer text from the pre-v0.3.0 flat ./config bind mount layout
├── tests/
│   └── smoke_admin.py   manual auth smoke test (not wired to a runner)
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── requirements.txt
├── CHANGELOG.md
└── README.md
```

`data/` (gitignored) is the runtime bind mount; its layout is in [config.md](config.md).

## Tech stack

| Layer      | Choice      | Rationale |
|------------|-------------|-----------|
| Backend    | FastAPI     | Async streaming for large video files; minimal boilerplate |
| Downloader | yt-dlp      | Widest site support; actively maintained |
| Frontend   | Vanilla JS  | No build step; single screen keeps it simple |
| Server     | uvicorn     | Pairs naturally with FastAPI |
| Container  | Docker      | Matches tiktok-downloader deployment pattern |
| Proxy      | Caddy       | TLS termination + reverse proxy to container |

## Containers

Two services in docker-compose.yml:

- `multi-downloader`: the app, port 8000 internal, on `caddy_net` (external network, Caddy routes traffic in) and `downloader_net`
- `bgutil-provider` (`brainicism/bgutil-ytdlp-pot-provider`): sidecar that generates visitor-level YouTube Proof of Origin tokens without a logged-in account, mitigating YouTube bot detection. On `downloader_net` only, an internal bridge with no path to `caddy_net`. The downloader reaches it at `BGUTIL_URL` (default `http://bgutil-provider:4416`), wired via yt-dlp's `youtubepot-bgutilhttp` extractor args

## Download flow

1. Frontend POSTs `/api/info` (on paste or debounced keystroke) to populate the preview card and quality selector.
2. `/api/download` runs yt-dlp in a thread (`asyncio.to_thread`), downloading to a fresh temp dir. `height` caps the resolution; null means best available. Output is remuxed to MP4 (see the remux gotcha in [gotchas.md](gotchas.md)).
3. The file is renamed to `{service}-{uploader}-{id}.{ext}`, where service is a shorthand tag (`yt`, `ig`, `tt`, `x`) or the extractor name, and unsafe filename characters are stripped.
4. The response streams the file with `Content-Disposition: attachment; filename*=UTF-8''...` and `Content-Length`; the temp dir is removed and the request logged when the stream finishes, complete or not.

Concurrency: a per-domain `asyncio.Semaphore(2)` caps simultaneous yt-dlp operations per platform domain to reduce rate-limit exposure. There is no per-user authentication or IP rate limiting on the public API; the semaphore is the only throttle.

## Frontend constraints

Single page, mobile-first. Key constraints:

- The Paste button uses the Clipboard API (`navigator.clipboard.readText()`), which requires a secure context (HTTPS or localhost); it degrades gracefully on HTTP
- Downloads fetch the response, read it chunk by chunk against `Content-Length` to show a percentage in the button, then hand the blob to a temporary `<a download>` element. This sidesteps iOS Safari opening large streaming responses inline
- Mobile download behaviour still varies by OS
- Theme (light/dark/system) is a `data-theme` attribute driven by `localStorage`, shared across the public page, the legal disclaimer page, and the admin UI

## Admin panel

Mounted at `/admin` in the same process, gated by an HTTP middleware in `app/admin.py` that requires a session for everything except the login routes and static files. The login page offers username/password (credentials generated on first launch, printed to the container output, stored hashed in `data/oauth.json`) and/or OpenID Connect (configured in the panel's Authentication section, restart to apply); the panel returns 404 entirely when neither method is usable. Sessions are signed cookies (Starlette `SessionMiddleware`, cookie `mdl_admin`, lifetime from oauth.json, default 7 days).

```
dl.yourdomain.com          ->  multi-downloader (port 8000)
dl.yourdomain.com/admin    ->  session auth (password / OIDC)  ->  admin panel
```

Security properties:

- All `/admin` routes require a session; `/admin/api/*` returns 401, pages redirect to the login page
- Passwords are PBKDF2-SHA256 hashed (600k iterations); comparison is constant-time (`hmac.compare_digest`); sessions are regenerated at login
- OIDC uses the authorization code flow with PKCE S256 and a state check
- Secrets live on the data volume only (`oauth.json` password hash and client secret, `.secret_key`); none are in the environment or the image. The OIDC client secret and password hash are write-only through the API (`client_secret_set` and `password_set` booleans instead)
- `AUTH_RESET=1` plus a restart is the lockout hatch: disables OIDC, regenerates admin credentials, prints them to the container output

The auth design is deliberately identical to nyshare's admin; see the unification gotcha in [gotchas.md](gotchas.md) before changing anything here.

## Request logging

Implemented in `app/db.py`; `/api/info` and `/api/download` log via `log_request()`, which is awaited inline (a local SQLite insert, a few ms) so writes cannot be lost to task garbage collection. Every call is written to `data/db/requests.db`:

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `ts` | TEXT | ISO 8601 timestamp (UTC) |
| `ip` | TEXT | Real client IP (see proxy headers below) |
| `country` | TEXT | ISO country code; null if GeoLite2 DB absent |
| `user_agent` | TEXT | Raw `User-Agent` header |
| `browser` | TEXT | Parsed browser name + version |
| `os` | TEXT | Parsed OS name + version |
| `device_type` | TEXT | `desktop`, `mobile`, or `tablet` |
| `endpoint` | TEXT | `info` or `download` |
| `url` | TEXT | URL submitted by the user |
| `success` | INTEGER | 1 on success, 0 on failure |
| `error` | TEXT | Error detail on failure |
| `filename` | TEXT | Output filename (download success only) |
| `filesize` | INTEGER | Bytes (download success only) |
| `duration_ms` | INTEGER | Wall-clock time for the operation |

The table is created with `CREATE TABLE IF NOT EXISTS` at startup; no migration tooling at this scale. Logging failures are silently swallowed: a DB write error must never interrupt or fail a download.

**Real IP behind Caddy:** `request.client.host` behind a reverse proxy gives the proxy's IP. `ProxyHeadersMiddleware` (from uvicorn, added in `public.py`) promotes `X-Forwarded-For` to `request.client.host`; Caddy passes the header by default. The same middleware supplies `X-Forwarded-Proto`, which makes the OIDC callback URL https.

**GeoIP (optional):** country resolution uses MaxMind's free GeoLite2 database. The app checks for `data/db/GeoLite2-Country.mmdb` at startup: present means country is resolved, absent means `country` stays null. MaxMind requires a free account to download and releases updates monthly.

## Testing

`tests/smoke_admin.py` is a manual auth smoke test, not wired to any runner: `DATA_DIR=/tmp/mdl-data python tests/smoke_admin.py`.
