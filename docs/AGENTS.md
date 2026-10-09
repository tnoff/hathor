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

**`hathor/database/migrate.py` and `hathor/database/migrations/`**
Alembic, configured in code (no `alembic.ini`). `migrate(engine, logger)` runs in `HathorClient.__init__` on one connection, so an in memory sqlite database is migrated on the connection the client then uses (`env.py` reads it from `config.attributes['connection']`). An existing database without `alembic_version` is stamped `0001` only after `check_baseline` confirms the baseline tables and columns; otherwise it raises, because stamping a schema that is not the baseline would make later migrations fail halfway. Revisions are hand-reviewed and use `batch_alter_table`. `script.py.mako` carries the pylint pragma generated files need (alembic's `op` is a runtime proxy). See [DEVELOPMENT.md](DEVELOPMENT.md#database-migrations).

**`hathor/podcast/archive.py`**
Archive backends behind `ArchiveInterface`. Three implementations:
- `RSSManager` — parses RSS feeds via `feedparser`, downloads files via HTTP (`curl_download`)
- `YoutubeManager` — uses Google API to list videos, downloads via `yt-dlp`. Before download, calls `videos.list` to check `liveBroadcastContent` / `liveStreamingDetails.actualEndTime` / `contentDetails.duration` and defers (returns `(None, None)`) when the video is live, upcoming, or a finished live still being processed into a VOD — those return to the queue for the next sync

  With `youtube_skip_shorts` set, listing also drops shorts. There is no api field for it, so `_is_short` HEADs `youtube.com/shorts/<id>`, which answers 200 for a short and 303 for anything else. It runs after the title filters, and a skipped short deliberately leaves `known_streak` alone, since it never enters `known_urls`. An unreachable player returns `None` rather than an answer, and such a video is left out of the walk's results entirely — the check only runs here, so anything stored is never re-examined, and leaving it unknown lets the next sync ask again. `YOUTUBE_SHORTS_UNKNOWN_STOP` consecutive `None`s end the walk, since nothing further can be classified either and each check costs a full timeout

  Listing reads the channel's uploads playlist via `playlistItems.list` (1 quota unit a call, against `search.list`'s 100) at `YOUTUBE_PAGE_SIZE` a page. Paging stops early on `YOUTUBE_KNOWN_STREAK_STOP` consecutive videos from the `known_urls` the client passes down, unless the client also passes `backfill` — a podcast under its `max_allowed` needs the episodes sitting *under* the known ones, which a walk that stops on them can never reach, so the streak is ignored and `max_results` (sized to the gap) ends the walk instead. Capped at `YOUTUBE_MAX_PAGES` either way. All calls go through `_execute`, which asks the google client for `YOUTUBE_NUM_RETRIES` retries (it backs off on 429/5xx/rate-limit 403s) and turns a spent quota into a `HathorException`
- `TwitchManager` — downloads past broadcasts (VODs) from a Twitch channel via the Helix API, authenticated with a client-credentials app token from `twitch_client_id`/`twitch_client_secret`. Live streams are skipped and picked up on a later sync once Twitch has finished processing the VOD.

`ARCHIVE_TYPES` dict maps string keys (`'rss'`, `'youtube'`, `'twitch'`) to classes. `HathorClient._archive_manager()` instantiates the right one.

**`HathorClient.episode_index`**
Writes `index_file` (json: podcasts by name, episodes newest first, each with `path` relative to `podcast_directory`, `size` from `stat`, `content_type`, readable `filename`) for something else to serve. Only episodes whose file exists under `podcast_directory` are included. Written with `utils.write_file_atomic` (temp file in the same directory, then `os.replace`) because the reader runs concurrently, e.g. a web server in another pod sharing the volume.

**`hathor/audio/metadata.py`**
Audio tag manipulation via `mutagen`. Used by `HathorClient.__episode_download_input` to set tags after download.

**`hathor/cli.py`**
Click-based CLI exposing all `HathorClient` methods. Config is loaded via `pyaml_env` from the path described in README.md.

**`hathor/audio/cli.py`**
Separate CLI (`audio-tool`) for direct audio file tag operations.

**`hathor/output.py`**
Shared `render_output(data, as_json)` used by both CLIs. Every command result flows through it: `--json` (stored in `ctx.obj['json']`, set by each group's root command) prints raw JSON via `json.dumps`; otherwise it renders a `dappertable` table -- columns from dict keys for a list of dicts, a `key`/`value` table for a single dict, one line per item for a list of scalars, and a bare `str()` for anything else.

### Sync failure handling

`episode_sync`, `podcast_sync` and `episode_download` isolate failures. The web sync of each podcast runs in `_episode_sync_podcast` and each download in `_episode_download_one`; both are called inside a `try/except Exception` that calls `_record_failure` (logs, **rolls the session back**, appends to a `failures` list) and carries on. The public method raises `SyncFailure` once, at the end, via `_raise_failures`. Raising only after the decorated helper returns means its plugin hooks still run. The private helpers take `failures`; `None` makes `_record_failure` re-raise, i.e. the old fail-fast behaviour. Error text goes through `utils.scrub_error` (URL query strings may hold credentials). Query objects are materialized with `list()` before iterating, since a rollback must not happen under a live cursor. Deletes (`__episode_delete_file_input`) are not isolated.

### Feeds

`hathor/feeds.py` only builds XML (`build_feed`, `build_opml`; ElementTree, hence the `nosec B405`: it never parses). `episode_index` collects richer episode data in the same pass as the index and, with `feeds_directory` set, `_write_feeds` writes `<slug>.xml` per podcast plus `podcasts.opml` atomically and deletes `.xml`/`.opml` files it did not write. `_feed_filenames` resolves slug collisions (`-<id>`) once, and that same name is passed to `build_feed` for the self link; compute it in two places and a renamed feed advertises the wrong URL. guids are `hathor-<podcast_id>-<episode_id>`, never the URL. Text goes through `xml_text` because descriptions come from the web and a single control character breaks the whole feed. Tests parse the output with `feedparser`, which is what a podcast app is. `feeds_directory` without `feed_base_url` fails at the end of `__init__` (so `__del__` has what it needs).

### Plugin System

Place Python files in `hathor/plugins/`, or set `plugins_directory` to load them from anywhere (`_load_external_plugins`: by file path with `importlib.util`, sorted, skipping `__init__.py` and anything hidden so a mounted ConfigMap's `..data` symlinks do not load each plugin three times; an explicit directory replaces the package one; a plugin that fails to import raises `HathorException`). They are auto-discovered at client init via `load_plugins()`. See [DEVELOPMENT.md](DEVELOPMENT.md#plugins) for the function signature, naming convention, and an example.

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
