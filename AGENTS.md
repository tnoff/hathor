# AGENTS.md

This file provides guidance to AI coding agents working in this repository. It documents code-internal structure that isn't covered by the user-facing docs.

For setup, test, and lint commands see [DEVELOPMENT.md](DEVELOPMENT.md). For user-facing usage (CLI, config schema, Docker, archive types) see [README.md](README.md).

## Architecture

### Core Components

**`hathor/client.py` — `HathorClient`**
The central class. All podcast and episode operations go through this. Uses SQLAlchemy with a configurable connection string (defaults to in-memory SQLite for tests). Key public methods follow the pattern `{resource}_{action}` (e.g., `podcast_create`, `episode_download`, `filter_list`).

All public methods are decorated with `@run_plugins`, which invokes matching plugin functions after the method returns.

**`hathor/database/tables.py`**
Three SQLAlchemy models: `Podcast`, `PodcastEpisode`, `PodcastTitleFilter`. Each has an `as_dict(datetime_output_format)` method for serialization.

**`hathor/podcast/archive.py`**
Archive backends behind `ArchiveInterface`. Two implementations:
- `RSSManager` — parses RSS feeds via `feedparser`, downloads files via HTTP (`curl_download`)
- `YoutubeManager` — uses Google API to list videos, downloads via `yt-dlp`. Before download, calls `videos.list` to check `liveBroadcastContent` / `liveStreamingDetails.actualEndTime` / `contentDetails.duration` and defers (returns `(None, None)`) when the video is live, upcoming, or a finished live still being processed into a VOD — those return to the queue for the next sync

  With `youtube_skip_shorts` set, listing also drops shorts. There is no api field for it, so `_is_short` HEADs `youtube.com/shorts/<id>`, which answers 200 for a short and 303 for anything else. It runs after the title filters, and a skipped short deliberately leaves `known_streak` alone, since it never enters `known_urls`. An unreachable player returns `None` rather than an answer, and such a video is left out of the walk's results entirely — the check only runs here, so anything stored is never re-examined, and leaving it unknown lets the next sync ask again. `YOUTUBE_SHORTS_UNKNOWN_STOP` consecutive `None`s end the walk, since nothing further can be classified either and each check costs a full timeout

  Listing reads the channel's uploads playlist via `playlistItems.list` (1 quota unit a call, against `search.list`'s 100) at `YOUTUBE_PAGE_SIZE` a page. Paging stops early on `YOUTUBE_KNOWN_STREAK_STOP` consecutive videos from the `known_urls` the client passes down, unless the client also passes `backfill` — a podcast under its `max_allowed` needs the episodes sitting *under* the known ones, which a walk that stops on them can never reach, so the streak is ignored and `max_results` (sized to the gap) ends the walk instead. Capped at `YOUTUBE_MAX_PAGES` either way. All calls go through `_execute`, which asks the google client for `YOUTUBE_NUM_RETRIES` retries (it backs off on 429/5xx/rate-limit 403s) and turns a spent quota into a `HathorException`

`ARCHIVE_TYPES` dict maps string keys (`'rss'`, `'youtube'`) to classes. `HathorClient._archive_manager()` instantiates the right one.

**`hathor/audio/metadata.py`**
Audio tag manipulation via `mutagen`. Used by `HathorClient.__episode_download_input` to set tags after download.

**`hathor/cli.py`**
Click-based CLI exposing all `HathorClient` methods. Config is loaded via `pyaml_env` from the path described in README.md.

**`hathor/audio/cli.py`**
Separate CLI (`audio-tool`) for direct audio file tag operations.

### Plugin System

Place Python files in `hathor/plugins/`. They are auto-discovered at client init via `load_plugins()`. See [DEVELOPMENT.md](DEVELOPMENT.md#plugins) for the function signature, naming convention, and an example.

### Test Layout

Tests mirror the package structure under `tests/`:
- `tests/podcasts/` — archive, episode, filter, and podcast client tests
- `tests/audio/` — metadata and audio CLI tests
- `tests/test_client.py`, `tests/test_cli.py`, `tests/test_utils.py` — top-level tests

Tests use an in-memory SQLite database (no connection string needed). The `pytest-mock` and `requests-mock` libraries are used for mocking external calls.

### Key Data Flow

1. `podcast_sync` → `__episode_sync_cluders` (fetches new episodes from archive) → `_podcast_download_episodes` (downloads files, respects `max_allowed`, deletes old files)
2. Episode files are named: `{date}.{normalized_title}` with extension determined by content-type
3. `prevent_deletion=True` on an episode exempts it from `max_allowed` cleanup
