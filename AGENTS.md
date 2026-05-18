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
