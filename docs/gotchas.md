# Decisions and gotchas

Non-obvious decisions and workarounds that look wrong until you know why.

## `ConfigUpdate` must mirror `Config`

`app/admin.py` has a Pydantic model `ConfigUpdate` that is separate from the `Config` dataclass in `config.py`. They must stay in sync. When adding a new config field, add it to `Config` in `config.py`, `_FIELDS` in `config.py`, AND `ConfigUpdate` in `admin.py`. Missing it from `ConfigUpdate` means the field is silently dropped on every save from the admin UI.

## Unified admin auth with nyshare

Routes (`/admin/login`, `/admin/oidc/login`, `/admin/oidc/callback`, `/admin/logout`), the oauth.json schema (`enabled`, `discovery_url`, `client_id`, `client_secret`, `session_lifetime_days`, `external_url`, `password_login`, `admin_username`, `admin_password_hash`, `must_change_password`), the Authentication settings UI semantics (secret write-only, restart-required banner, `AUTH_RESET=1` as lockout hatch, generated first-launch credentials printed to the container output, at-least-one-method validation, password login only disableable while OIDC is running), enable rule (password or OIDC configured) and login page layout are deliberately identical to nyshare's admin. Change one, change both.

The OIDC flow and oauth.json storage were ported from social-downloader (authlib + PKCE); IdP front-channel logout was dropped on purpose to keep the id_token out of the cookie session. oauth.json is read once at import time in `app/auth.py`; a restart applies changes (password and username changes are read fresh and apply immediately).

## Starlette mount paths

In the admin sub-app, `request.scope["path"]` contains the FULL path (`/admin/api/config`), not the stripped remainder; only `root_path` marks the mount. The auth middleware strips `root_path` manually. `request.base_url` already includes the mount prefix, so the OIDC callback URL fallback is built from `base_url` alone.

## Admin frontend uses relative URLs

Everything in `static/admin/` fetches `api/...` (no leading slash) so paths resolve under `/admin/`. Starlette redirects `/admin` to `/admin/`, which makes relative resolution work. A leading `/` would escape the mount and hit the public app.

## Legal disclaimer is a file, not a config field

`data/legal/disclaimer.md` is read from `LEGAL_DIR` (derived from `DATA_DIR`) on each request. It is intentionally not in `config.json`: it is a document, not a setting, and is edited directly on the bind-mounted volume. If the file does not exist or is empty, the disclaimer notice and the `/legal-disclaimer` route are both suppressed.

## Cookies: one shared file, checked per call

Some sites only serve content to logged-in users (the common case: NSFW posts on X/Twitter). A Netscape-format `cookies.txt` uploaded via the admin panel's Content section (or placed at `data/cookies.txt` directly) is passed to yt-dlp; the downloader checks for the file on every call, so no restart is needed. One shared file covers all sites since yt-dlp only sends cookies matching the request domain. yt-dlp also writes refreshed cookies back to the file after each run, so rotated session tokens persist; concurrent downloads can race on that write, which is harmless in practice (last writer wins).

Upload time lives in the companion `data/cookies.timestamp` file because st_mtime is unreliable on Docker volume mounts.

## MP4 remux: use the postprocessor, not `remux_video`

The CLI-style `remux_video` option is silently ignored by the yt-dlp Python API. `downloader.py` uses the `FFmpegVideoRemuxer` postprocessor instead, which remuxes single-stream downloads to MP4 without re-encoding and skips files that are already MP4.

## Request logging must never fail a download

`log_request()` swallows all exceptions; a DB write error must never interrupt or fail a download. The insert is awaited inline (not fired as an untracked task) because untracked tasks were garbage-collected mid-write and dropped entries.

## Data volume is mounted read-write

The container needs to write `data/db/requests.db`, so the whole volume is rw. Config safety relies on the admin UI being the only writer of `config.json`, not on an OS-level `:ro` mount.
