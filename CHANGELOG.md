# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-11

### Added
- Mobile-first single-page web frontend with URL input, Paste button, and Download button
- Video preview (thumbnail, title, duration, uploader) triggered on paste or URL input
- FastAPI backend with streaming download endpoint (`POST /api/download`)
- Metadata endpoint (`POST /api/info`) for video preview lookups
- yt-dlp integration as primary download engine; ffmpeg used for format muxing
- Input field cleared when download begins; preview and status banner auto-dismiss after 3 seconds
- Static file cache-busting via `APP_VERSION` build arg baked into query strings
- Static files served from the FastAPI process — no separate web server required
- Docker image published to GHCR (`ghcr.io/nikolainyegaard/multi-downloader`), multiplatform (amd64 + arm64)
- `docker-compose.yml` for deployment behind Caddy reverse proxy
- `BUILD_VERSION` build arg baked into image as `APP_VERSION` env var

[Unreleased]: https://github.com/nikolainyegaard/multi-downloader/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nikolainyegaard/multi-downloader/releases/tag/v0.1.0
