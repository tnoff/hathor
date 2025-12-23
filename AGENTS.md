# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

Hathor is a Python package for downloading and maintaining media files, with a focus on podcasts. It supports downloading from RSS feeds and YouTube channels, storing metadata in a database, and managing local podcast episode files.

**For AI Assistants:** This document contains architecture details, development workflows, and project-specific conventions to help you be productive when contributing to this codebase.

## Development Commands

### Initial Setup

**Local Development:**
```bash
# Install in development mode
pip install -e .

# Install with test dependencies
pip install -r requirements.txt
pip install -r tests/requirements.txt

# Create configuration file
hathor init --podcast-dir ~/Podcasts
```

**Docker Setup:**
```bash
# Build the Docker image
docker-compose build

# Initialize configuration (creates config in volume)
docker-compose run --rm hathor hathor init

# Edit config to add Google API key if needed
# Config is stored in the 'hathor-config' Docker volume
# View config location: docker volume inspect hathor_hathor-config

# Run any hathor command
docker-compose run --rm hathor hathor podcast list

# Or run as daemon for repeated commands
docker-compose up -d
docker-compose exec hathor hathor podcast sync
docker-compose down
```

### Testing and Linting
```bash
# Run full test suite with linting and coverage (requires 95% coverage)
# Note: Tests use in-memory database via HATHOR_USE_MEMORY_DB env var
tox

# Run tests directly with pytest
pytest --cov=hathor/ --cov-report=html --cov-fail-under=95 tests/

# Run tests for a single module
pytest tests/podcasts/test_episodes.py

# Run a specific test
pytest tests/podcasts/test_episodes.py::TestClassName::test_method_name

# Lint main code
pylint hathor/

# Lint test code (uses different config)
pylint --rcfile .pylintrc.test tests/
```

### Building
```bash
python setup.py build
```

### Common Usage Examples
```bash
# Initialize config
hathor init

# Create a podcast
hathor podcast create rss "https://example.com/feed.xml" "My Podcast"

# List podcasts (simple)
hathor podcast list

# List podcasts (verbose with full details)
hathor podcast list -v

# Sync all podcasts
hathor podcast sync

# Sync specific podcasts
hathor podcast sync -i 1 -i 3

# List episodes with files only
hathor episode list -f

# Protect an episode from deletion
hathor episode protect 123
```

## Architecture

### Core Components

**HathorClient** (`hathor/client.py`)
- Main client class that orchestrates all podcast operations
- Manages SQLAlchemy database session for all persistence operations
- Coordinates between archive managers, database tables, and audio metadata handling
- Loads and runs plugins via decorator pattern on client methods

**Archive Managers** (`hathor/podcast/archive.py`)
- `ArchiveInterface`: Base class defining the interface for archive sources
- `RSSManager`: Handles RSS feed parsing and downloads using feedparser
- `YoutubeManager`: Handles YouTube downloads using yt-dlp and Google API
- Each manager implements `broadcast_update()` to fetch episodes and `episode_download()` to download media

**Database Tables** (`hathor/database/tables.py`)
- `Podcast`: Stores podcast metadata (name, archive_type, broadcast_id, max_allowed episodes, etc.)
- `PodcastEpisode`: Stores episode metadata (title, download_url, file_path, file_size, etc.)
- `PodcastTitleFilter`: Stores regex filters for filtering episodes by title
- Uses SQLAlchemy ORM with declarative base

**CLI Interfaces**
- `hathor/cli.py`: Main hathor CLI using Click framework for podcast management
- `hathor/audio/cli.py`: Separate audio-tool CLI for audio file metadata operations

### Configuration

Hathor follows the XDG Base Directory specification for configuration:
- **Config file**: `~/.config/hathor/config.yml` (or `XDG_CONFIG_HOME/hathor/config.yml`)
- **Legacy location**: `~/.hathor_config.yml` (still supported for backwards compatibility)
- **Database**: `~/.local/share/hathor/hathor.db` (or `XDG_DATA_HOME/hathor/hathor.db`)

Configuration file has two sections:
- `hathor`: Client configuration (podcast_directory, database_connection_string, google_api_key, datetime_output_format)
- `logging`: Logging configuration passed to utils.setup_logger

Key features:
- Configuration is validated on load with warnings for missing recommended fields
- Use `hathor init` to generate a default configuration file
- Configuration can be overridden with `-c` flag
- Tests use in-memory database when `HATHOR_USE_MEMORY_DB` env var is set

### Plugin System

Plugins extend client functionality by running after core methods:
- Plugins are Python files placed in `hathor/plugins/` directory
- Plugin functions must match the client method name they extend (e.g., `__episode_sync_with_filters` plugin runs after episode sync)
- Plugin signature: `def method_name(self, results, *args, **kwargs)` where self is the HathorClient instance
- Plugins must return results which become the new return value of the client method
- Plugins are loaded at client initialization via `load_plugins()` and executed via `@run_plugins` decorator
- Example plugin: `youtube_extractor.py` extracts YouTube URLs from RSS episodes and creates entries in a separate podcast

**Creating New Plugins:**
1. Create a `.py` file in `hathor/plugins/`
2. Define a function with the exact name of the client method to hook into
3. Function signature: `def method_name(self, results, *args, **kwargs)`
4. Process the results and return modified or original results
5. Access the database via `self.db_session`
6. Use `self.logger` for logging
7. Plugin is automatically loaded on next client initialization

**Note:** The `hathor/plugins/` directory is in `.gitignore` to allow users to maintain custom plugins without committing them.

### Data Flow

1. **Podcast Sync**: `HathorClient.podcast_sync()` → Archive manager's `broadcast_update()` → Creates/updates PodcastEpisode records → Downloads episodes via archive manager's `episode_download()` → Updates audio file metadata
2. **Episode Management**: Episodes can be synced without downloading (`episode_sync`) or downloaded individually (`episode_download`)
3. **Max Allowed Enforcement**: When max_allowed is set, oldest episodes beyond the limit are automatically deleted unless `prevent_deletion` is True

### Archive Types

- `rss`: RSS feed downloads using feedparser and direct HTTP downloads
- `youtube`: YouTube channel downloads using yt-dlp with Google API for metadata
- Archive type determines which manager class handles broadcast updates and downloads
- Broadcast ID: For RSS it's the feed URL, for YouTube it's the channel ID

### Audio Metadata

The `hathor/audio/metadata.py` module uses mutagen library to:
- Read/update ID3 tags and other audio metadata
- Embed/extract album artwork
- Set artist, album, title, and other standard tags on downloaded episodes

## CLI Design Principles

The CLI was refactored (2025) with these improvements that should be maintained in future changes:

- **Positive flags**: Use `--auto-download/--no-auto-download` instead of `--no-auto-download`
- **Boolean flags for protection**: `episode protect` command with `--unprotect` flag (instead of boolean argument)
- **Multiple option support**: `--include/-i` and `--exclude/-e` can be used multiple times instead of comma-separated
- **Confirmation prompts**: Destructive operations (`delete`, `cleanup`) require confirmation unless `--yes/-y` is passed
- **Better command naming**: `podcast move` instead of `podcast update-file-location`, `episode protect` instead of `episode update`
- **Short options**: Common flags have short versions (`-i`, `-e`, `-y`, `-v`, `-f`, `-m`, `-a`)
- **Colored output**: Success messages in green, errors in red using click.secho
- **Comprehensive help**: All commands have detailed docstrings with argument descriptions

**When adding new CLI commands:**
1. Follow the existing naming patterns
2. Add both long and short options for common flags
3. Include confirmation prompts for destructive actions
4. Use colored output for user feedback
5. Write detailed help text with parameter descriptions
6. Prefer positive flags over negative ones

## Common Pitfalls and Gotchas

**Database:**
- The database uses UTC internally but displays dates according to `datetime_output_format`
- `as_dict()` converts datetime objects to strings - when creating new records from dict data, parse dates back to datetime objects
- SQLite doesn't support certain datetime operations - test date handling carefully

**Podcasts:**
- YouTube downloads require a Google API key in the config
- RSS feeds may have varying quality - handle missing fields gracefully
- Patreon URLs have special handling (see `utils.check_patreon()` and `utils.process_url()`)

**File Operations:**
- Always use `Path` objects from `pathlib`, not string paths
- Check if files exist before operations
- Handle file permissions errors gracefully

**Testing:**
- Always set `HATHOR_USE_MEMORY_DB=1` when running tests
- Clean up temporary files created during tests
- Don't rely on specific podcast/episode IDs in tests

## Docker Support

Hathor includes Docker support with proper volume mounts for persistence:

### Docker Volumes
- **hathor-config**: Stores configuration at `/data/config/hathor/config.yml`
- **hathor-db**: Stores SQLite database at `/data/db/hathor/hathor.db`
- **podcasts**: Mapped to `./podcasts` by default (customizable)

### Key Features
- Auto-initialization: Creates default config on first run if none exists
- FFmpeg pre-installed for audio processing
- XDG-compliant directory structure
- Persistent storage for config, database, and downloaded podcasts

### Dockerfile
- Based on `python:3.12-slim`
- Includes ffmpeg for audio processing
- Sets up XDG environment variables
- Entrypoint script handles config initialization

### Customization
Copy `docker-compose.override.yml.example` to `docker-compose.override.yml` to:
- Change podcast directory location
- Add environment variables (Google API key)
- Set up cron jobs for automatic syncing
- Customize resource limits

## Testing Notes

- Tests use in-memory SQLite databases via `HATHOR_USE_MEMORY_DB` environment variable
- Mock RSS feeds and responses are in `tests/data/rss_feed.py`
- Audio tests require ffmpeg (installed in CI via FedericoCarboni/setup-ffmpeg)
- Use `tests/utils.py` helpers like `temp_audio_file()` for generating test audio files
- Click CLI testing uses `CliRunner` with YAML config files in temp locations
- When writing tests, set `HATHOR_USE_MEMORY_DB=1` to avoid creating persistent database files

**Test Coverage Requirements:**
- Maintain 95% code coverage (enforced by tox)
- All new features must include tests
- Use pytest fixtures from `tests/utils.py`
- Mock external API calls (RSS feeds, YouTube API)

## Code Style and Conventions

**Python Style:**
- Follow PEP 8 with exceptions defined in `.pylintrc`
- Use type hints for function signatures (see `client.py` for examples)
- Disabled pylint checks: line-too-long, missing-module-docstring, too-few-public-methods, logging-fstring-interpolation, too-many-arguments, too-many-positional-arguments, too-many-locals, singleton-comparison

**Naming Conventions:**
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_CASE`
- Private methods: `_leading_underscore` or `__double_underscore` for name mangling
- Avoid abbreviations like "cluders" - use descriptive names

**Database Conventions:**
- Use SQLAlchemy ORM for all database operations
- Models are in `hathor/database/tables.py`
- Always commit within the same method that creates/updates records
- Use `as_dict()` method to serialize database objects to JSON

**Error Handling:**
- Use specific exception types from `hathor/exc.py`
- Provide user-friendly error messages in CLI
- Log errors with appropriate log levels
- Clean up resources in finally blocks

## File References

When discussing code, reference specific files and line numbers:
- Client logic: `hathor/client.py`
- CLI commands: `hathor/cli.py`
- Audio tools CLI: `hathor/audio/cli.py`
- Archive managers: `hathor/podcast/archive.py`
- Database models: `hathor/database/tables.py`
- Audio metadata: `hathor/audio/metadata.py`
- Utilities: `hathor/utils.py`
- Exceptions: `hathor/exc.py`
- Plugin loader: `hathor/client.py:42-68` (load_plugins and run_plugins functions)
