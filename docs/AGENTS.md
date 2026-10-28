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

  With `youtube_skip_shorts` set, listing also drops shorts. There is no api field for it, so `_is_short` HEADs `youtube.com/shorts/<id>`, which answers 200 for a short and a 3xx to `/watch` for anything else; any other answer (429, 5xx, a consent redirect) is `None`. It runs after the title filters, and a skipped short deliberately leaves `known_streak` alone, since it never enters `known_urls`. An unreachable player returns `None` rather than an answer, and such a video is left out of the walk's results entirely — the check only runs here, so anything stored is never re-examined, and leaving it unknown lets the next sync ask again. `YOUTUBE_SHORTS_UNKNOWN_STOP` consecutive `None`s end the walk, since nothing further can be classified either and each check costs a full timeout

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

### Telemetry

`hathor/telemetry.py`: opt-in OTLP logs and traces from the standard `OTEL_*` variables (http/protobuf only), set up the way the discord apps do it. `setup_otlp()` runs once when the module is imported and does nothing without an endpoint: it sets the global `TracerProvider` / `LoggerProvider` (with `BatchSpanProcessor` / `BatchLogRecordProcessor` and the OTLP http exporters) and turns on `RequestsInstrumentor`. Code makes spans with `TRACER.start_as_current_span(...)` like any OpenTelemetry user (a no-op without a provider), and `HathorClient.__init__` calls `telemetry.attach(self.logger)` to add the stock `LoggingHandler` to its logger. Flush on exit is the SDK's own atexit shutdown, so there is no `close()` or flush hook of ours. Rules that are easy to break:

- **Take env variable names from `opentelemetry.sdk.environment_variables` / `opentelemetry.environment_variables`**, never write them out, and no `pylint:disable` for imports. The packages are required dependencies imported at the top like any other.
- **Masking is the custom part, and it is on the way out**: `MaskingSpanExporter` wraps the span exporter and hides credentials in urls in every attribute, status and recorded exception of every span, ours or an instrumentation's (`requests` puts the full url, query string and all, in `http.url`, and urllib3's `ConnectionError` names the path and query: `utils.mask_log_text` handles that `url: /path?query` form). `MaskingFilter` is on the log handler and gives it a copy of the record with the message and traceback masked and the extra fields dropped. A new instrumentation or a new span attribute needs no masking code of its own; do not bypass the exporter (do not add a second processor or exporter on the provider).
- **Telemetry must not fail or slow a sync**: `setup_otlp` catches whatever setting up raises and logs a warning, exports run on the SDK's background threads with a 3 second request timeout, and nothing waits on them except the SDK's shutdown as the process exits.
- **SQLAlchemy is not instrumented**: `opentelemetry-instrumentation-sqlalchemy` declares `sqlalchemy < 2.1` and, with the check skipped, wraps `sqlalchemy.ext.asyncio`, which needs `greenlet` that hathor does not install. Revisit when it supports 2.1.
- `exit_on_sigterm()` (installed by the CLI when traces are on) turns SIGTERM into `SystemExit` so the run unwinds, ending its open spans, and exits normally, which is when the SDK sends what is queued. `SystemExit` is not an `Exception`, so those spans are not marked as errors.
- Tests (`tests/test_telemetry.py`) call `setup_otlp()` with the in-memory exporters substituted for `_span_exporter` / `_log_exporter`; OpenTelemetry only lets a provider be set once, so `reset_otel()` there puts the globals back between tests. `requests_mock` replaces `Session.send` and bypasses the instrumentation, so the `requests` tests use a local HTTP server.

### Sync failure handling

`episode_sync`, `podcast_sync` and `episode_download` isolate failures. The web sync of each podcast runs in `_episode_sync_podcast` and each download in `_episode_download_one`; both are called inside a `try/except Exception` that calls `_record_failure` (logs, **rolls the session back**, appends to a `failures` list) and carries on. The public method raises `SyncFailure` once, at the end, via `_raise_failures`. Raising only after the decorated helper returns means its plugin hooks still run. The private helpers take `failures`; `None` makes `_record_failure` re-raise, i.e. the old fail-fast behaviour. Error text goes through `utils.scrub_error` (URL query strings may hold credentials). Query objects are materialized with `list()` before iterating, since a rollback must not happen under a live cursor. Deletes (`__episode_delete_file_input`) are not isolated.

### Feeds

`hathor/feeds.py` only builds XML (`build_feed`, `build_opml`; ElementTree, hence the `nosec B405`: it never parses). `episode_index` collects richer episode data in the same pass as the index and, with `feeds_directory` set, `_write_feeds` writes `<slug>.xml` per podcast plus `podcasts.opml` atomically and deletes `.xml`/`.opml` files it did not write. `_feed_filenames` resolves slug collisions (`-<id>`) once, and that same name is passed to `build_feed` for the self link; compute it in two places and a renamed feed advertises the wrong URL. guids are `hathor-<podcast_id>-<episode_id>`, never the URL. Text goes through `xml_text` because descriptions come from the web and a single control character breaks the whole feed. Tests parse the output with `feedparser`, which is what a podcast app is. `feeds_directory` without `feed_base_url` fails at the end of `__init__` (so `__del__` has what it needs).

### Podcast artwork

`podcast_update(image=..., remove_image=...)`. `hathor/artwork.py` (`load_image`) reads a url or file and trusts only the magic bytes (`image_extension`), capped at `MAX_IMAGE_BYTES`, then `_decode`s it with Pillow: a full decode (so a corrupt file is refused), a `MAX_IMAGE_PIXELS` check before the bitmap is allocated (Pillow's own decompression bomb warning is turned into a refusal too), and a shrink to `MAX_IMAGE_SIDE` only when larger (smaller images are returned byte for byte; the extension can change on a shrink, which `podcast_update` already handles by removing the old file); it runs *before* `podcast_update` mutates anything, so a refused image leaves everything as it was. The file lands in `<podcast_directory>/.artwork/<id>.<ext>` and `Podcast.image` holds the path relative to `podcast_directory` (so a remounted volume still resolves); `_image_path` only returns a file that exists inside that directory, which keeps a hand-edited `../x` from being copied into the served feeds. The old file is removed after the commit. `episode_index` resolves it per podcast (`image_source`), `_feed_images` names the served copy with a hash of the content (a changed image must be a new url, since apps cache artwork by url), and `_write_feeds` copies it if not already there and passes `image_url` to `build_feed`, which writes `itunes:image` and `image` together. The cleanup pass removes files with `artwork.IMAGE_EXTENSIONS` suffixes as well as `.xml`/`.opml`, so a replaced or removed image copy goes. Error text goes through `utils.scrub_error`/`mask_url_secrets` because signed image urls carry tokens. The column was added by the first real Alembic revision, `0002`.

### Logging and masking

`utils.setup_logger` gives its handlers a `MaskingFormatter`, which runs `mask_log_text` over the *finished* line (message with its %-args and any traceback, so an exception's text is covered too). `mask_log_text` finds every `scheme://...` in the text: http(s) goes through `mask_url_secrets`, anything else (a database connection string) loses only its password. This exists because DEBUG logs print feed and episode URLs and a private Patreon feed has its key in `?auth=`; hathor's `--json`/table output is masked separately by `mask_config_secrets`. A logger handed to `HathorClient(logger=...)` bypasses it, and anything new that logs a secret outside a URL (a bare token) needs masking at the call site. Progress lines are INFO: `Syncing episodes of podcast N (name)` / `Podcast N (name): X new episodes` in `__episode_sync_cluders` and `Downloading episode N of podcast P (name): title` in `_episode_download_one`; keep URLs out of them. Tests: `tests/test_log_masking.py` includes a client run at DEBUG that asserts neither a feed key nor an episode-url token reaches the log file.

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
