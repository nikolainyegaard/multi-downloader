# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Mobile-first single-page web frontend with URL input, Paste button, and Download button
- FastAPI backend with streaming download endpoint (`POST /api/download`)
- yt-dlp integration as primary download engine; ffmpeg used for format muxing
- Static files served from the FastAPI process — no separate web server required
- Docker image published to GHCR (`ghcr.io/nikolainyegaard/multi-downloader`), multiplatform (amd64 + arm64)
- `docker-compose.yml` for deployment behind Caddy reverse proxy
- `BUILD_VERSION` build arg baked into image as `APP_VERSION` env var
