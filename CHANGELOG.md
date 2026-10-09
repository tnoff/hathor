# Changelog

All notable changes to hathor will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.9.2] - 2026-10-09

### Changed

- `hathor dump-config` now hides credentials, which it printed in full: any setting whose name contains `key`, `secret`, `token` or `password` (everything beneath it too), the path of `feed_base_url` (the URL token lives there; the host stays), the password in a database connection string, and the query string, fragment and `user:password@` of any URL, such as a proxy in `ytdlp_options`. Unset values still read as unset. `--show-secrets` prints everything as before. Matching is by name, so a new credential setting with an unusual name is not hidden: check the output when adding one. Only what is printed changes; the client still gets the real config.

## [2.9.1] - 2026-10-09

### Changed

- `podcast list`, `podcast show`, `podcast create`, `podcast update`, `podcast update-file-location` and `podcast delete` now hide the query string, fragment and any `user:password@` of a feed URL in `broadcast_id` when printing, since a private feed (Patreon) carries its key there. `podcast list` and `podcast show` take `--show-secrets` to print them in full. Only what is printed changes: the database, the client API and plugins still get the real value. A key placed in the URL path itself cannot be detected and is not hidden.

### Fixed

- A `HathorClient` whose `__init__` failed early (a bad config value, for example) printed `AttributeError: 'HathorClient' object has no attribute 'db_session'` from `__del__` on top of the real error, hiding it. `close()` now tolerates a client that never finished initialising.

## [2.9.0] - 2026-10-09

### Added

- `feeds_directory` and `feed_base_url` settings: `hathor index` also writes an RSS 2.0 feed (with the iTunes tags podcast apps look for) for every podcast that has episodes on disk, and a `podcasts.opml` that imports them all at once, so a podcast app such as AntennaPod can subscribe and download new episodes by itself. Item guids are `hathor-<podcast id>-<episode id>` and never depend on a URL; enclosures carry the real size and content type; file names are percent encoded and text that XML cannot carry is dropped. Feeds are written atomically and feed files no longer wanted are removed. `index.json` gains `feed` per podcast and `opml` so a page can link to them. `feeds_directory` without `feed_base_url` is an error.

## [2.8.2] - 2026-10-09

### Changed

- Bumped google-api-python-client to v2.201.0

## [2.8.1] - 2026-10-09

### Changed

- Bumped sqlalchemy to v2.1.4

## [2.8.0] - 2026-10-09

### Changed

- A failure in one podcast no longer stops the whole sync. `podcast sync`, `episode sync` and `episode download` now log and skip a podcast whose feed fails (web sync) or an episode that fails to download, carry on with the rest (including downloads and plugin hooks for the podcasts that did sync), and raise a single `SyncFailure` at the end listing every failure, so the exit code and a scheduled job's status still show the problem. Previously the first unexpected error aborted the run: a malformed feed URL skipped every podcast after it. The exception carries `failures` and `results`. The session is rolled back after each failure so one bad commit cannot break the following podcasts.
- URL query strings and fragments are removed from error text in logs and in `SyncFailure`, since a private feed URL carries its key there.

## [2.7.0] - 2026-10-08

### Added

- `plugins_directory` setting: load plugins from any directory instead of the package's own `hathor/plugins/`, so a container can mount them (for example from a Kubernetes ConfigMap) without baking them into the image or mounting into a Python-version-specific `site-packages` path. Plugins load by file path, in sorted order; `__init__.py` and hidden files and directories are skipped (a mounted ConfigMap holds each file three times); an explicit directory replaces the package one; what is loaded is logged, a missing or empty directory warns, and a plugin that fails to import raises `HathorException` naming the file. Default behaviour is unchanged.

## [2.6.1] - 2026-10-08

### Fixed

- `hathor index` wrote `index.json` with mode `0600`: the atomic write goes through a temp file, which is created `0600`, and the rename kept it. Anything reading the index as another user, such as a web server sharing the volume, got a 403. The index (and `utils.write_file_atomic` generally) is now written `0644`.

## [2.6.0] - 2026-10-07

### Added

- `hathor index` writes a json index of every episode file under `podcast_directory` to the new `index_file` setting, grouped by podcast with the newest episodes first, each with its relative path, size, content type and a readable file name. The file is replaced atomically. Supports `--dry-run`.

## [2.5.2] - 2026-10-07

### Changed

- Bumped google-api-python-client to v2.200.0

## [2.5.1] - 2026-10-07

### Changed

- Bumped sqlalchemy to v2.1.3

## [2.5.0] - 2026-09-24

### Changed

- Both `hathor` and `audio-tool` now print a formatted table by default instead of raw JSON, using a new shared `dappertable`-backed renderer: a list of records becomes a table keyed on the record's fields, a single record becomes a key/value table, and a list of ids or similar prints one per line. Pass `--json` before the subcommand (e.g. `hathor --json podcast list`) to get the old raw JSON output back for scripting.

## [2.4.4] - 2026-09-18

### Changed

- Bumped sqlalchemy to v2.0.54

## [2.4.3] - 2026-08-28

### Changed

- Bumped google-api-python-client to v2.199.0
- Bumped click to v8.5.0

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
