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
  twitch_client_id: abc1234
  twitch_client_secret: xyz9876
  datetime_output_format: "%Y-%m-%d"
  youtube_skip_shorts: true
  ytdlp_options:
    sleep_requests: 1
    sleep_interval: 2
    max_sleep_interval: 6
logging:
  logging_file: /home/user/foo.log
  console_logging: true
  log_level: 10
  logging_file_backup_count: 5
  logging_file_max_bytes: 102400
```

#### yt-dlp Options

`ytdlp_options` is passed through to yt-dlp when downloading a youtube or twitch archive.
It is merged over hathor's own options, so it can override the download format
or add anything yt-dlp accepts, for example a `proxy`. The output template and
logger are not overridable, since hathor reads the downloaded file path back out
of the result and routes yt-dlp's output through its own logger.

The pacing keys shown above are the defaults. They exist because youtube rate
limits an unpaced client: downloading a backlog back to back returns `HTTP Error
429` on the first request of each video, which escalates into `Sign in to confirm
you're not a bot`, and from then on nothing downloads until the client backs off.
`sleep_requests` spaces out requests within a single extraction, while
`sleep_interval` and `max_sleep_interval` put a randomised gap in front of each
download. Raise them if you are still being throttled; lower them at your own
risk.

#### YouTube Shorts

Shorts sit in a channel's uploads playlist next to everything else, so by default a
youtube podcast picks them up like any other video. Set `youtube_skip_shorts: true`
to leave them out of syncs.

The data API has no field that marks a video as a short, and duration is not a
reliable stand in — shorts run up to three minutes and plenty of regular uploads
are shorter than that. Hathor asks the shorts player instead: it answers `200` for
a real short and redirects anything else to `/watch`. That costs no API quota, but
it is one extra request per video that reaches the check, so the check runs only
after the title filters have had their say. A video is kept whenever the check
cannot be made, so an unreachable youtube drops nothing.

Skipped shorts are never stored as episodes, which means each sync re-checks the
ones still inside the window it walks.

### Podcast Archives

When creating a new podcast record, users will need to specify where the podcast will be downloaded
from, we call that the "archive". The following archives are supported:

- Youtube
- Twitch
- RSS Feeds

#### Google API Keys

To download podcasts from youtube, users will need a [Google API secret key](https://console.developers.google.com).

This can be placed in the settings file under `google_api_key`, or passed directly when initializing the client.

#### Twitch API Credentials

To download podcasts from twitch, users will need to register an application in the
[Twitch developer console](https://dev.twitch.tv/console/apps), which gives a client ID and a client secret.

These can be placed in the settings file under `twitch_client_id` and `twitch_client_secret`, or passed
directly when initializing the client. Hathor only reads public data, so it authenticates with the client
credentials grant and no twitch user ever has to log in.

#### Broadcast ID

The broadcast ID is the unique identifier for a podcast within its archive.

For **RSS**, the broadcast ID is the feed URL:

```
$ hathor podcast create "rss" "https://example.com/feed.rss" "podcast-name"
```

For **Youtube**, the broadcast ID is the channel ID from the channel URL. For example, given
`https://www.youtube.com/channel/UC27vDmUZpQjuJFFkUz8ujtg`, the broadcast ID is `UC27vDmUZpQjuJFFkUz8ujtg`.

You may need to use 3rd party tools to find the channel ID of a particular uploader, such as [ytlarge](https://ytlarge.com/youtube/channel-id-finder/).

Note: when a YouTube live broadcast has just ended, hathor will skip the download until YouTube finishes producing the on-demand VOD (usually minutes to a couple hours, depending on length). The episode is automatically retried on the next sync.

Note: syncing reads the channel's uploads playlist, which costs 1 unit of the
YouTube Data API's daily quota per 50 videos. Videos come back newest first, and
a sync stops paging as soon as it reaches episodes it already has, so a routine
sync of a channel with nothing new costs a single call. A sync will read at most
1000 videos of a channel's back catalogue, so the first sync of a very large
channel may need to run more than once to reach the oldest uploads.

For **Twitch**, the broadcast ID is the channel login name, the last part of the channel URL. For example, given
`https://www.twitch.tv/somechannel`, the broadcast ID is `somechannel`:

```
$ hathor podcast create "twitch" "somechannel" "podcast-name"
```

Only past broadcasts are fetched. Channel highlights and uploaded videos are left alone.

Note: a broadcast that is still live, or one that twitch has not finished processing into a VOD, is skipped
and retried on the next sync, so a partial stream is never downloaded.

Note: twitch deletes VODs on a schedule, after 7 days for most channels and 14 days for Affiliates and
Partners. Unlike the other archives, if a sync does not run inside that window the broadcast is gone before
hathor ever sees it, so twitch podcasts need syncs to run on a reliable schedule. Past broadcasts are also
usually much larger than podcast episodes, so consider setting `max_allowed` on the podcast.


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

## Docker

Build the image:

```bash
docker build -t hathor .
```

Create a config file pointing to container paths:

```yaml
---
hathor:
  podcast_directory: /podcasts
  database_connection_string: sqlite:////data/hathor.sql
  google_api_key: abc1234
logging:
  logging_file: /data/hathor.log
  console_logging: true
  log_level: 20
```

Run a podcast sync, mounting your local directories:

```bash
docker run --rm \
  -v /home/user/podcasts:/podcasts \
  -v /home/user/hathor-data:/data \
  -v /home/user/hathor-config:/config \
  hathor -c /config/hathor_config.yml podcast sync
```

To use `audio-tool`, override the entrypoint:

```bash
docker run --rm \
  --entrypoint audio-tool \
  -v /home/user/podcasts:/podcasts \
  hathor tags-show /podcasts/episode.mp3
```

### Egressing Through a VPN

Syncing a youtube archive makes two kinds of outbound call: the yt-dlp media
fetch, and a YouTube Data API call that defers episodes still live or still
processing. Setting a yt-dlp proxy would only cover the first, so the simplest
complete option is to put the whole container inside a VPN container's network
namespace.

With [gluetun](https://github.com/qdm12/gluetun) and a WireGuard key:

```yaml
services:
  gluetun:
    image: docker.io/qmcgaw/gluetun:v3.41.3
    cap_add:
      - NET_ADMIN
    devices:
      - /dev/net/tun:/dev/net/tun
    environment:
      VPN_SERVICE_PROVIDER: mullvad
      VPN_TYPE: wireguard
      WIREGUARD_PRIVATE_KEY: ${WIREGUARD_PRIVATE_KEY}
      WIREGUARD_ADDRESSES: ${WIREGUARD_ADDRESSES}
      # gluetun picks one hostname per connection and holds it for the life of
      # the container. Prefer an explicit hostname list to SERVER_CITIES: a
      # multi-city list sticks to a single city (gluetun #3328), and a hostname
      # list is the only way to drop one specific exit server from rotation.
      # Check these against your gluetun version: unrecognised names are only
      # WARNed about ("are not in choices") and then silently dropped, which
      # shrinks the pool without failing anything.
      SERVER_HOSTNAMES: us-lax-wg-101,us-sjc-wg-302,us-chi-wg-201

  hathor:
    image: hathor
    # Excluded from `docker compose up`; `docker compose run` still starts it.
    profiles: ["cli"]
    network_mode: "service:gluetun"
    depends_on:
      gluetun:
        condition: service_healthy
    # Downloads land owned by this uid rather than root.
    user: "1000:1000"
    volumes:
      - /home/user/podcasts:/podcasts
      - /home/user/hathor-data:/data
      - /home/user/hathor-config:/config
    entrypoint: ["hathor", "-c", "/config/hathor_config.yml"]
```

```bash
docker compose run --rm hathor podcast sync
```

A few things worth knowing:

- Episode file paths are stored in the database as absolute paths. If the
  container shares a database with a non-container hathor, mount each host
  directory at the *same* absolute path inside the container — remapping the
  library under `/podcasts` will leave the database pointing at files the
  container cannot see.
- gluetun's firewall acts as a killswitch. If the tunnel drops, hathor loses
  network access rather than falling back to the default route.
- A sync that fails with `HTTP Error 403: Forbidden` on the media fetch, while
  extraction of the same video succeeds, means the exit IP has been flagged
  rather than the episode being unavailable. Remove that server from
  `SERVER_HOSTNAMES` and recreate the gluetun container to move to a new exit.

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for instructions on setting up a local dev environment, running tests, and writing plugins.
