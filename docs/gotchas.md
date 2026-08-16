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

## TikTok photo posts go through the embed page

yt-dlp's TikTok extractor only matches `/video/` URLs, so photo posts fail with "Unsupported URL". The obvious fix (scraping `__UNIVERSAL_DATA_FOR_REHYDRATION__` from the photo page, like social-downloader does) does not work here: TikTok bot-walls that page for clients without a logged-in session or a browser TLS fingerprint, and social-downloader only gets away with it because it always sends real session cookies. The embed page (`tiktok.com/embed/v2/{id}`) serves the same photo data to anyone, plain TLS included, so `downloader.py` parses its `__FRONTITY_CONNECT_STATE__` JSON instead and fetches the images directly with httpx. Note the embed page uses different key names than the main page (`imagePostInfo.displayImages[].urlList` vs `imagePost.images[].imageURL.urlList`).

Share links (vm.tiktok.com, vt.tiktok.com, tiktok.com/t/) are resolved with a redirect-following GET before the photo check, because they hide the `/photo/` path behind a redirect and yt-dlp's short-link extractor would resolve them to an unsupported URL.

## YouTube community post images: SOCS cookie and =s0

Community posts (`youtube.com/post/{id}`) are also unsupported by yt-dlp, and yt-dlp does not download images anyway. The post page is public, but two tricks are load-bearing in `downloader.py`: the `SOCS=CAI` cookie skips the EU consent redirect that would otherwise replace the page, and the image URLs in `ytInitialData` are square-cropped WebP previews whose trailing `=s{size}-...` params must be rewritten to `=s0` to get the full-resolution original (this flips the response to JPEG). The `backstagePostRenderer` is found by recursive key search because its path inside `ytInitialData` is not stable.

## Instagram and X photo posts: gallery-dl as fallback, not first choice

yt-dlp always gets the first attempt on Instagram and X URLs so video posts keep the quality selector and MP4 remux. Only when yt-dlp raises a DownloadError AND the URL is post-shaped (instagram.com `/p/`, `/reel/`, `/tv/`; twitter.com or x.com `/status/`) does `downloader.py` retry with gallery-dl, which resolves the post's media URLs without downloading them itself. If gallery-dl also fails, the original yt-dlp error is raised, not gallery-dl's.

X tweet resolution works logged out (verified; gallery-dl returns `name=orig` full-resolution image URLs). Instagram redirects every logged-out client to the login page, so Instagram posts only work when the uploaded cookies.txt contains Instagram cookies; the file is passed to gallery-dl on every call, same no-restart behaviour as yt-dlp. The service tag for filenames comes from the extractor object's `category` attribute ("twitter", "instagram"), which is not present in the per-message metadata dicts.

## Request logging must never fail a download

`log_request()` swallows all exceptions; a DB write error must never interrupt or fail a download. The insert is awaited inline (not fired as an untracked task) because untracked tasks were garbage-collected mid-write and dropped entries.

## Data volume is mounted read-write

The container needs to write `data/db/requests.db`, so the whole volume is rw. Config safety relies on the admin UI being the only writer of `config.json`, not on an OS-level `:ro` mount.
