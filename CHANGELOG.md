# Changelog

All notable changes to hathor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.4.2] - 2026-08-26

### Changed

- An unanswered shorts check no longer stores the video as a regular episode. The check only runs while walking a channel's listing, so anything that gets past it is never looked at again -- a stretch where the shorts player was unreachable therefore archived every short it could not classify, permanently. Such a video is now left out of the sync entirely rather than guessed at, so the next sync gets to ask again, and a run of failed checks in a row ends the walk instead of spending a full timeout on every remaining video in the channel.

## [2.4.1] - 2026-08-22

### Changed

- A podcast under its `max_allowed` now backfills instead of staying short. Youtube listing walks newest first and stops once it has seen a few episodes it already has, which is right for a podcast that is only ever gaining episodes but leaves one that has LOST them stuck: the episodes needed to fill the gap are older than the ones still stored, so the walk turns back before it ever reaches them. Deleting episodes, or turning on a setting that filters some out, could strand a podcast under its limit for good. A sync now measures the gap and asks the listing to walk past what it knows, stopping as soon as the gap is filled.

## [2.4.0] - 2026-08-22

### Changed

- Youtube podcasts can now leave shorts out of a sync, with the new `youtube_skip_shorts` setting (off by default, so nothing changes for existing configs). Shorts live in a channel's uploads playlist alongside everything else and the data api has no field that marks one, so hathor asks the shorts player, which answers 200 for a real short and redirects anything else to /watch. The check costs no api quota and runs only after the title filters, so it is spent only on videos that would otherwise be stored, and a video is kept whenever the check cannot be made.

## [2.3.3] - 2026-08-21

### Changed

- Bumped yt-dlp to v2026.8.19

## [2.3.2] - 2026-08-16

### Changed

- A youtube or twitch broadcast that is not downloadable yet, because it is live, upcoming, or still being processed into a VOD, is now skipped quietly during a sync instead of being logged as "Unable to download episode". The liveness checks already held these back, but they returned the same empty result as a genuine download failure, so every sync reported an error for an episode that was only waiting on the broadcast. The episode still keeps no file and is picked up again by a later sync once the broadcast is ready.

## [2.3.1] - 2026-08-14

### Changed

- Bumped sqlalchemy to v2.0.52

## [2.3.0] - 2026-08-13

### Changed

- Youtube episode syncs now read a channel's uploads playlist through `playlistItems.list` instead of `search.list`. The two return the same fields, but `search.list` costs 100 units of the 10,000 unit daily API quota per call while `playlistItems.list` costs 1. Page size is also set explicitly to 50, the maximum; the API default of 5 was spending a call on every fifth video.
- A sync now stops paging once it sees three videos in a row that are already stored, so a routine sync of a channel with nothing new costs one call instead of walking the whole back catalogue. Known videos are recognised before the title filters run, so a filter that rarely matches can no longer keep a walk going to the oldest upload.
- Paging is capped at 20 pages per sync, so no single podcast can page through an entire channel. The first sync of a very large channel may need to run more than once to reach the oldest uploads.
- Youtube API calls now ask the google client for retries, so transient 429s and rate-limit 403s back off and retry instead of failing the sync. An exhausted daily quota raises a plain "Youtube api daily quota exceeded" error rather than a raw HttpError.
- Archive managers are built once per client instead of once per episode, so a download run reuses one google API client and one twitch access token.

## [2.2.1] - 2026-08-13

### Changed

- Moving a podcast's files to a new location now works when the old and new directories are on different filesystems, or on different mount points of the same filesystem. The move used os.rename, which fails with an "Invalid cross-device link" error in both cases, the second being what two bind mounts of one drive look like inside a container.
- The new file location is written to the database only after the files have been moved, and the old directory is no longer deleted when it resolves to the same directory as the new one. A failed move used to leave the podcast pointing at the new directory while the files were still in the old one, and re-running the command from that state deleted every file it had just moved.

## [2.2.0] - 2026-08-13

### Changed

- Added a twitch archive type, for downloading a channel's past broadcasts. The broadcast ID is the channel login name, and hathor fetches past broadcasts only, leaving channel highlights and uploaded videos alone. Needs a twitch_client_id and twitch_client_secret from a registered twitch application.
- A broadcast that is still live, or one twitch has not finished processing into a VOD, is skipped and retried on the next sync, so a partial stream is never downloaded.

## [2.1.19] - 2026-08-12

### Changed

- Youtube downloads are now paced by default (sleep_requests, sleep_interval, max_sleep_interval). Downloading a backlog back to back was returning HTTP 429 and then the "Sign in to confirm you're not a bot" page, after which nothing would download.
- Added a ytdlp_options setting, merged over hathor's own yt-dlp options, so the pacing can be tuned and anything else yt-dlp accepts (a proxy, a different format) can be set. The output template and logger stay under hathor's control.

## [2.1.18] - 2026-08-11

### Changed

- Added ffmpeg to the docker image. Youtube serves most formats as separate video and audio streams, and yt-dlp aborts the download rather than degrading when it has nothing to merge them with, so youtube archives could not be downloaded from the image at all.
- Added the deno javascript runtime to the docker image so yt-dlp can solve youtube's JS challenges (EJS). Without a runtime yt-dlp warns that some formats may be missing and drops the formats behind a challenge.

## [2.1.17] - 2026-07-31

### Changed

- Bumped feedparser to v6.0.14

## [2.1.16] - 2026-07-10

### Changed

- Bumped yt-dlp to v2026.7.4

## [2.1.15] - 2026-07-04

### Changed

- Bumped sqlalchemy to v2.0.51

## [2.1.14] - 2026-07-04

### Changed

- Bumped google-api-python-client to v2.198.0

## [2.1.13] - 2026-07-04

### Changed

- Bumped mutagen to v1.48.1

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
