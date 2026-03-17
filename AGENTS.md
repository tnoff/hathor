# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Commands

**Install:**
```bash
pip install -e .
pip install -r requirements.txt -r tests/requirements.txt
```

**Run all tests with lint and coverage:**
```bash
tox
```

**Run tests only (no lint):**
```bash
pytest --cov=hathor/ --cov-report=html --cov-fail-under=95 tests/
```

**Run a single test file:**
```bash
pytest tests/podcasts/test_archive.py
```

**Run a single test:**
```bash
pytest tests/podcasts/test_archive.py::TestClassName::test_method_name
```

**Lint:**
```bash
pylint hathor/
pylint --rcfile .pylintrc.test tests/
```

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
- `YoutubeManager` — uses Google API to list videos, downloads via `yt-dlp`

`ARCHIVE_TYPES` dict maps string keys (`'rss'`, `'youtube'`) to classes. `HathorClient._archive_manager()` instantiates the right one.

**`hathor/audio/metadata.py`**
Audio tag manipulation via `mutagen`. Used by `HathorClient.__episode_download_input` to set tags after download.

**`hathor/cli.py`**
Click-based CLI exposing all `HathorClient` methods. Config is loaded from `~/.hathor_config.yml` (or `-c` flag) via `pyaml_env`. The config has `hathor:` and `logging:` sections.

**`hathor/audio/cli.py`**
Separate CLI (`audio-tool`) for direct audio file tag operations.

### Plugin System

Place Python files in `hathor/plugins/`. Functions named after a `HathorClient` method will be called after that method with signature `(client, result, *args, **kwargs)` and must return the result. Plugins are auto-discovered at client init via `load_plugins()`.

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
