# Hathor

Hathor is a python package that is designed to help users download and maintain media files, focusing on podcasts.

Includes support for the following feed types:
- RSS
- Youtube


## Installation

Clone the repo from github and use pip to install:

```
git clone https://github.com/tnoff/hathor.git
pip install hathor/
```

### What Is Installed

The ``hathor`` python module will be installed, as well as 2 cli scripts:

- `hathor` — downloading and managing podcast media files
- `audio-tool` — reading and modifying metadata on audio files

## The Hathor Client

The hathor client is the main component of hathor. Using the hathor cli or hathor python
package, it is possible to create new podcast records, update them, and download the latest episodes.

You can use hathor with the command line:

    hathor podcast --help

### Initialization and Settings

These variables can be loaded from a settings file. The default location of this settings file
is the home directory, under ``~/.hathor_config.yml``. It can also be specified on the command line
with the ``-c`` flag.

There should be two sections, `hathor` and `logging`:

```yaml
---
hathor:
  podcast_directory: /home/user/foo
  database_connection_string: sqlite:////home/user/foo.sql
  google_api_key: abc1234
  datetime_output_format: "%Y-%m-%d"
logging:
  logging_file: /home/user/foo.log
  console_logging: true
  log_level: 10
  logging_file_backup_count: 5
  logging_file_max_bytes: 102400
```

### Podcast Archives

When creating a new podcast record, users will need to specify where the podcast will be downloaded
from, we call that the "archive". The following archives are supported:

- Youtube
- RSS Feeds

#### Google API Keys

To download podcasts from youtube, users will need a [Google API secret key](https://console.developers.google.com).

This can be placed in the settings file under `google_api_key`, or passed directly when initializing the client.

#### Broadcast ID

The broadcast ID is the unique identifier for a podcast within its archive.

For **RSS**, the broadcast ID is the feed URL:

```
$ hathor podcast create "rss" "https://example.com/feed.rss" "podcast-name"
```

For **Youtube**, the broadcast ID is the channel ID from the channel URL. For example, given
`https://www.youtube.com/channel/UC27vDmUZpQjuJFFkUz8ujtg`, the broadcast ID is `UC27vDmUZpQjuJFFkUz8ujtg`.

You may need to use 3rd party tools to find the channel ID of a particular uploader, such as [ytlarge](https://ytlarge.com/youtube/channel-id-finder/).


### Downloading Podcasts

With an archive type and broadcast ID, create a new podcast record:

```
$ hathor podcast create "rss" "http://example.foo/rss/feed" "podcast-name"
```

Run a podcast sync to check for new episodes and download them:

```
$ hathor podcast sync
```

List episodes:

```
# Only episodes with downloaded files
$ hathor episode list --only-files
# All episodes
$ hathor episode list
```

Sync episode metadata without downloading files:

```
$ hathor episode sync
```

Download a specific episode by ID:

```
$ hathor episode download <episode-id>
```

#### Max Allowed

The "max allowed" option controls how many episode files are kept at one time. For example, if
max allowed is set to 5, hathor will keep the five latest episodes and delete any older files.

```
$ hathor podcast update <podcast-id> --max-allowed 5
```

To remove the limit and keep all episodes, set it to 0:

```
$ hathor podcast update <podcast-id> --max-allowed 0
```

To prevent a specific episode from being deleted by max allowed:

```
$ hathor episode update <episode-id> True
```

#### Episode Filters

Episode filters control which episodes are added to the database and downloaded, matched against
episode titles using regexes.

```
$ hathor filter create <podcast-id> <regex-filter>
```

## The Audio Tool

`audio-tool` provides standalone commands for reading and modifying audio file metadata.

Show tags on an audio file:

```
$ audio-tool tags-show <file>
```

Update tags on an audio file (comma-separated `key=value` pairs):

```
$ audio-tool tags-update <file> "artist=My Artist,album=My Album"
```

Update the cover art on an audio file:

```
$ audio-tool picture-update <audio-file> <image-file>
```

Extract cover art from an audio file:

```
$ audio-tool picture-extract <audio-file> <output-file>
```

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for instructions on setting up a local dev environment, running tests, and writing plugins.
