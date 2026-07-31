# API routes

## Public app (`app/public.py`)

**`GET /`**: serves `index.html` with config placeholders replaced server-side (`__VERSION__`, `__BROWSER_TITLE__`, `__ACCENT_COLOR__`, `__PASTE_HIDDEN__`, `__FAVICON_LINK__`, `__HEADER_CONTENT__`, `__DISCLAIMER_NOTICE__`, `__DEV_BANNER__`, `__KOFI_SCRIPT__`)

**`GET /legal-disclaimer`**: renders `data/legal/disclaimer.md` as an HTML page using mistune; 404 when the file is absent or empty

**`GET /logo`**: the uploaded logo (`data/static/logo.avif` or `.webp`); 404 when none

**`GET /favicon.ico`** and **`GET /apple-touch-icon.png`**: uploaded favicons (`favicon-32.png` / `favicon-180.png` from `data/static/`); 404 when none

**`POST /api/info`**
- Body: `{ "url": "https://..." }`
- Response: `{ title, thumbnail, duration, uploader, qualities }`
- `qualities`: array of `{ label, height }` sorted best-first; the frontend adds a "Best" option that sends `height: null`
- Used by the frontend to populate the video preview and quality selector before downloading

**`POST /api/download`**
- Body: `{ "url": "https://...", "height": 720 }` (height optional; null or omitted = best available)
- Response: `StreamingResponse` with `Content-Disposition: attachment; filename*=UTF-8''<encoded>` and `Content-Length`
- yt-dlp downloads to a temp dir; the file is streamed to the client and the temp dir cleaned up when the stream ends

Static mounts, mounted last so API routes take priority:
- **`/assets/*`**: user-uploaded assets (logo, favicons) from `data/static/`
- **`/static/*`**: bundled public frontend files

## Admin app (mounted at `/admin`, `app/admin.py`)

Everything under `/admin` requires a session (401 for `/admin/api/*`, redirect to the login page for pages) except the auth routes and `/admin/static/*`. When no login method is configured, every route returns 404 with a hint to set `AUTH_RESET=1`.

### Auth (`app/auth.py`, public)

**`GET /admin/login`**: login page (username/password form and/or OpenID Connect button, depending on what is configured)

**`POST /admin/login`**: password login against the stored credentials in oauth.json (PBKDF2 hash, constant-time compare); creates a fresh session

**`GET /admin/oidc/login`**: redirect to the OIDC provider (authlib, PKCE S256, scopes `openid profile email`)

**`GET /admin/oidc/callback`**: code exchange, session creation

**`POST /admin/logout`**: clears the session

### Auth settings

**`GET /admin/api/auth/config`**: OIDC and password login settings; secrets come back as `client_secret_set` / `password_set` booleans, plus the `enabled_runtime` flag (saved vs running drift) and `must_change_password`

**`POST /admin/api/auth/config`**: saves oauth.json; blank `client_secret` or `new_password` keeps the stored one; 400 when enabling OIDC without all three fields, when both login methods would end up off, or when disabling password login while OIDC is not already running; OIDC changes need a restart to apply

### Pages

**`GET /admin/`**: admin UI (`index.html` with placeholders replaced; accent color converted to hue-derived hsl variables)

**`GET /admin/disclaimer-guide`**: hardcoded setup guide for the legal disclaimer file (not a bind-mount file)

**`GET /admin/favicon.ico`** and **`GET /admin/apple-touch-icon.png`**: same uploaded favicons as the public app

### Config

**`GET /admin/api/config`**: current `config.json` as JSON (defaults if no file exists) plus computed read-only fields `has_logo`, `has_favicon`, `has_disclaimer`

**`POST /admin/api/config`**: accepts a full config object, writes atomically to `config.json`

**`POST /admin/api/config/reset`**: overwrites `config.json` with built-in defaults

**`POST /admin/api/dismiss-disclaimer-warning`**: sets `show_disclaimer_warning: false` in `config.json` (backs the dismissible banner shown when `disclaimer.md` is absent)

### Branding

**`POST /admin/api/logo/upload`**: multipart upload; transparent padding trimmed, aspect ratio validated (1:1 to 5:1, wider than tall), scaled to fit 480x160, saved as pending AVIF (WebP fallback)

**`GET /admin/api/logo`** / **`GET /admin/api/logo/pending`**: serve the live / pending logo

**`POST /admin/api/logo/confirm`**: promotes the pending logo and sets `header_mode: "logo"`

**`POST /admin/api/logo/discard`**: deletes the pending logo

**`DELETE /admin/api/logo`**: deletes the live logo and sets `header_mode: "title"`

**`POST /admin/api/favicon/upload`**: any image, center-cropped to square, saved pending at 32x32 and 180x180 PNG

**`GET /admin/api/favicon/pending`** / **`POST /admin/api/favicon/confirm`** / **`POST /admin/api/favicon/discard`** / **`DELETE /admin/api/favicon`**: same pending/confirm lifecycle as the logo

### Cookies

**`GET /admin/api/cookies`**: `{present, size_bytes, updated_at}` for `data/cookies.txt`

**`POST /admin/api/cookies/upload`**: multipart upload of a Netscape-format cookies.txt; rejects files without at least one valid cookie line; writes atomically and stamps `data/cookies.timestamp` (st_mtime is unreliable on Docker volume mounts)

**`DELETE /admin/api/cookies`**: removes the cookies file and its timestamp

### Stats and logs

**`GET /admin/api/stats`**: totals (requests, downloads, errors), per-platform download counts (top 8, domain parsed from the URL), and a 14-day daily ok/err series; `{available: false}` when no DB exists yet

**`GET /admin/api/logs?page=&per_page=`**: paginated request log, newest first; `per_page` clamped to 1-500

Static mounts: **`/admin/assets/*`** (user assets) and **`/admin/static/*`** (bundled admin frontend files).
