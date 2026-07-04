# Changelog

All notable changes to hathor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.12] - 2026-07-04

### Changed

- Bumped yt-dlp to v2026.6.9

## [2.1.11] - 2026-06-28

### Changed

- Bumped click to v8.4.2

## [2.1.10] - 2026-05-30

### Changed

- Bumped google-api-python-client to v2.197.0

## [2.1.9] - 2026-05-25

### Changed

- Bumped sqlalchemy to v2.0.50

## [2.1.8] - 2026-05-23

### Changed

- Bumped click to v8.4.1

## [2.1.7] - 2026-05-18

### Fixed

- YouTube live broadcasts that have just ended are now deferred until their VOD is fully processed, so `yt-dlp` no longer downloads an audio-only artifact from the still-live HLS manifest. The episode is retried on the next sync.

### Changed

- `yt-dlp` format selector for YouTube downloads now prefers h264 (AVC) video with AAC audio, falling back to VP9, then any video+audio mux, then any single stream. This avoids AV1 — which is broadly available on YouTube but still trips up many playback stacks (Linux VLC hardware decode, smart TVs, Plex/Jellyfin transcoders, older browsers).

## [2.1.6] - 2026-05-18

### Changed

- Bumped click to v8.4.0

## [2.1.5] - 2026-05-15

### Changed

- Bumped requests to v2.34.2

## [2.1.4] - 2026-05-14

### Changed

- Bumped requests to v2.34.1

## [2.1.3] - 2026-05-12

### Changed

- Bumped requests to v2.34.0

## [2.1.2] - 2026-05-10

### Added
- GitLab Release is now published automatically on each new tag, with release notes pulled from the matching CHANGELOG section
- Renovate MRs now bump CHANGELOG.md alongside VERSION via the shared bump-version template's BUMP_CHANGELOG option

### Changed
- Source tarballs attached to GitLab Releases now contain only the runnable package plus install metadata (`LICENSE.rst`, `pyproject.toml`, `VERSION`); tests, CI configs, Dockerfile, and top-level docs are excluded via `.gitattributes`
