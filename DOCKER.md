# Docker Quick Reference

## Common Commands

### First Time Setup
```bash
# Build the image
docker-compose build

# Initialize configuration
docker-compose run --rm hathor hathor init

# Verify installation
docker-compose run --rm hathor hathor --help
```

### Managing Podcasts
```bash
# Create a podcast
docker-compose run --rm hathor hathor podcast create rss "https://feeds.example.com/podcast.xml" "My Podcast"

# List all podcasts
docker-compose run --rm hathor hathor podcast list

# Show podcast details
docker-compose run --rm hathor hathor podcast show 1

# Sync all podcasts
docker-compose run --rm hathor hathor podcast sync

# Sync specific podcast
docker-compose run --rm hathor hathor podcast sync -i 1

# Delete a podcast (with confirmation)
docker-compose run --rm hathor hathor podcast delete 1
```

### Managing Episodes
```bash
# List episodes with files
docker-compose run --rm hathor hathor episode list -f

# Show episode details
docker-compose run --rm hathor hathor episode show 123

# Download specific episode
docker-compose run --rm hathor hathor episode download 123

# Protect episode from deletion
docker-compose run --rm hathor hathor episode protect 123
```

### Volume Management
```bash
# List volumes
docker volume ls | grep hathor

# Inspect config volume
docker volume inspect hathor_hathor-config

# Inspect database volume
docker volume inspect hathor_hathor-db

# Backup config
docker run --rm -v hathor_hathor-config:/data -v $(pwd):/backup alpine tar czf /backup/hathor-config-backup.tar.gz /data

# Backup database
docker run --rm -v hathor_hathor-db:/data -v $(pwd):/backup alpine tar czf /backup/hathor-db-backup.tar.gz /data

# Remove all volumes (WARNING: deletes all data)
docker-compose down -v
```

### Configuration
```bash
# Get a shell to edit config
docker-compose run --rm hathor bash
# Then: vi /data/config/hathor/config.yml

# View config
docker-compose run --rm hathor cat /data/config/hathor/config.yml

# Dump current config
docker-compose run --rm hathor hathor dump-config
```

### Running as Daemon
```bash
# Start in background
docker-compose up -d

# Execute commands in running container
docker-compose exec hathor hathor podcast sync

# View logs
docker-compose logs
docker-compose logs -f  # Follow logs

# Stop daemon
docker-compose down
```

### Troubleshooting
```bash
# Get a shell
docker-compose run --rm hathor bash

# Check if config exists
docker-compose run --rm hathor ls -la /data/config/hathor/

# Check if database exists
docker-compose run --rm hathor ls -la /data/db/hathor/

# Check podcast directory
docker-compose run --rm hathor ls -la /data/podcasts/

# Rebuild image (after code changes)
docker-compose build --no-cache

# View container logs
docker-compose logs hathor
```

## Volume Locations

Inside the container:
- Config: `/data/config/hathor/config.yml`
- Database: `/data/db/hathor/hathor.db`
- Podcasts: `/data/podcasts/`

On the host (for named volumes):
- Use `docker volume inspect <volume_name>` to find the actual path
- Typically in `/var/lib/docker/volumes/`

## Environment Variables

You can set these in `docker-compose.override.yml`:

```yaml
services:
  hathor:
    environment:
      - XDG_CONFIG_HOME=/data/config
      - XDG_DATA_HOME=/data/db
      - PYTHONUNBUFFERED=1
```

## Custom Podcast Directory

Edit `docker-compose.override.yml`:

```yaml
services:
  hathor:
    volumes:
      - /path/to/your/podcasts:/data/podcasts
```

## Scheduled Syncing

Create `docker-compose.override.yml` with cron:

```yaml
services:
  hathor:
    # Install cronie first
    command: >
      sh -c "
      apk add --no-cache dcron &&
      echo '0 */6 * * * hathor podcast sync' > /etc/crontabs/root &&
      crond -f -l 2
      "
```

Or use host cron:
```cron
# Add to host crontab
0 */6 * * * docker-compose -f /path/to/hathor/docker-compose.yml run --rm hathor hathor podcast sync
```
