# Hathor

Hathor is a python package that is designed to help users download and maintain media files, focusing on podcasts.

Includes support for the following feed types:
- RSS
- Youtube


## Installation

### Local Installation

Clone the repo from github and use pip to install:

```bash
git clone https://github.com/tnoff/hathor.git
pip install hathor/
```

### Docker Installation

Use Docker for an isolated environment with all dependencies pre-installed:

```bash
# Clone and build
git clone https://github.com/tnoff/hathor.git
cd hathor
docker-compose build

# Initialize configuration
docker-compose run --rm hathor hathor init

# Run commands
docker-compose run --rm hathor hathor podcast create rss "https://example.com/feed.xml" "My Podcast"
docker-compose run --rm hathor hathor podcast sync
```

See the [Docker section](#docker-usage) below for more details.

### What Is Installed

The ``hathor`` python module will be installed, as well as 2 cli scripts:

``hathor``
    Used for downloading and managing podcast media files

``audio-tool``
    Used for modifying metadata on audio files

## The Hathor Client

The hathor client is the main component of hathor. Using the hathor cli or hathor python
package, it is possible to create new podcast records, update them, and download the latest episodes.

You can use hathor with the command line::

    hathor podcast --help

### Initialization and Settings

When the hathor client is initialized, certain variables must be specified. These
are better documented in the codebase.

These variables can also be loaded from a settings file. The default location of this settings file
is the home directory, under ``~/.hathor_config.yml``. It can also be specified in the command line
with the ``-c`` flag.


There should be two sections, `hathor` and `logging`. Logging args are sent directly to the `utils.setup_logger` method, `hathor` args are sent directly to the `HathorClient` class.

Options include

```
---
hathor:
  podcast_directory: /home/user/foo
  database_connection_string: sqlite:////home/user/foo.sql
  google_api_key: abc1234
  datetime_output_format = %Y-%m-%d
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

To download podcasts from youtube, users will need to create credentials
that can be used for their APIs.

For youtube users will need a `google api secret key <https://console.developers.google.com>`_.

These can be either placed in the settings file, or specified when initializing hathor.


#### Broadcast ID

The broadcast ID for a podcast is the unique identifier for that podcast when downloading
it from its archive.

For Youtube, if given the following url `https://www.youtube.com/channel/UC27vDmUZpQjuJFFkUz8ujtg`,
the broadcast id will be the last portion of the url, in this case `UC27vDmUZpQjuJFFkUz8ujtg`.

You may need to use 3rd party tools to find the channel ID of a particular uploader, such as [ytlarge](https://ytlarge.com/youtube/channel-id-finder/).


### Downloading Podcasts

With a archive type and broadcast id, users can then create a new podcast record using the cli:

```
$ hathor podcast create "rss" "http://example.foo/rss/feed" "podcast-name"
```

After the podcast has been created, users can then run a podcast sync, which will check the web
for new episodes, and then download the latest to the local machine:

```
$ hathor podcast sync
```

You can then list the podcast episodes to check for new episodes:

```
# Will only list episodes with files
$ hathor episode list --only-files
# Will list all episodes
$ hathor episode list
```

Alternatively, you can sync podcast episodes without downloading them:

```
$ hathor episode sync
```

To download podcast episodes individually:

```
$ hathor episode download <episode-id>
```

#### Max Allowed

The option "max allowed" controls how many podcast episode files are kept
at one time. For example, if max allowed is set to 5, hathor will download the five latest
episodes, and delete any that remain. Alternatively, this can be set to "None" to download all
possible episodes.

To set max allowed on a podcast:

```
$ hathor podcast update <podcast-id> --max-allowed <max-allowed-int>
```

It is possible to prevent the deletion of a file from max allowed restrictions.
If the user sets "prevent delete" to True, it will not be deleted by
a podcast sync command. To update the podcast episode use:

```
$ hathor episode update <episode-id> True
```

#### Episode filters Filters

Episode filters can be used to control which podcast episodes will be
added to the database and downloaded via regexes.

To add podcast filters:

```
$ hathor filter create <podcast-id> <regex-filter>
```

## Plugins

Plugins can be added for most functions in the hathor client.

Any plugins will have to be written in python and be placed in the
``hathor/plugins/`` directory.

Plugins should be named after the function you want them to run after,
for example if the plugin function is named "episode_download", it will be
run after the episode_download client function is complete.

Plugin functions should take 4 argument the first being the hathor client
(self), and the second being the result of the original client function, and the next being the `*args` and `**kwargs` the original function was called with.

Plugins should also return a result, that will be treated as the result of the
client function.

Take the following plugin function for example:

```

    # the following is in hathor/plugins/fix_title.py
    from hathor.database.tables import PodcastEpisode

    def episode_download(self, results, *args, **kwargs):
        for episode in results:
            if episode['podcast_id'] in [2, 3, 5]:
                episode['title'] = 'some fancy title'
                episode_obj = self.db_session.query(PodcastEpisode).get(episode['id'])
                episode_obj.title = 'some fancy title'
                self.db_session.commit()
        return results
```

This will change the title of new episodes for certain podcasts. Note that for the change
to be permanent, you'll have to change the episodes in the database.

## Docker Usage

Hathor includes Docker support with persistent volumes for configuration, database, and podcasts.

### Quick Start

```bash
# Build the image
docker-compose build

# Initialize configuration (only needed once)
docker-compose run --rm hathor hathor init

# Create a podcast
docker-compose run --rm hathor hathor podcast create rss "https://example.com/feed.xml" "My Podcast"

# Sync podcasts
docker-compose run --rm hathor hathor podcast sync

# List episodes
docker-compose run --rm hathor hathor episode list
```

### Persistent Storage

Hathor uses Docker volumes for persistence:

- **hathor-config**: Configuration file at `/data/config/hathor/config.yml`
- **hathor-db**: SQLite database at `/data/db/hathor/hathor.db`
- **podcasts**: Downloaded files at `/data/podcasts` (mapped to `./podcasts` by default)

### Configuration

The Docker entrypoint automatically creates a default configuration on first run. To customize:

1. Get a shell in the container:
   ```bash
   docker-compose run --rm hathor bash
   ```

2. Edit the config file:
   ```bash
   vi /data/config/hathor/config.yml
   ```

3. Or inspect the volume location:
   ```bash
   docker volume inspect hathor_hathor-config
   ```

### Adding Google API Key

To enable YouTube downloads, add your API key to the config:

```bash
# Get a shell
docker-compose run --rm hathor bash

# Edit config
vi /data/config/hathor/config.yml

# Add this line under the 'hathor:' section:
#   google_api_key: YOUR_KEY_HERE
```

### Running as a Daemon

For automatic syncing, run Hathor as a background service:

```bash
# Start daemon
docker-compose up -d

# Run commands via exec
docker-compose exec hathor hathor podcast sync
docker-compose exec hathor hathor podcast list

# View logs
docker-compose logs -f

# Stop daemon
docker-compose down
```

### Customization

Create a `docker-compose.override.yml` file (see `docker-compose.override.yml.example`) to:

- Change the podcast directory location
- Add environment variables
- Set up automatic syncing with cron
- Customize resource limits

Example override for custom podcast directory:

```yaml
version: '3.8'

services:
  hathor:
    volumes:
      - /mnt/media/podcasts:/data/podcasts
```

### Scheduled Syncing

To set up automatic syncing, create `docker-compose.override.yml`:

```yaml
version: '3.8'

services:
  hathor:
    command: >
      sh -c "
      echo '0 */6 * * * hathor podcast sync' | crontab - &&
      crond -f
      "
```

This will sync all podcasts every 6 hours.